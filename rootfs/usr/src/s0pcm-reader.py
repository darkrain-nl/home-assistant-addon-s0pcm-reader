
import datetime
import time
import threading
import serial
import yaml
import logging
from logging.handlers import RotatingFileHandler
import paho.mqtt.client as mqtt
import ssl
import argparse
import copy
import json
import os

"""
Description
-----------
This small Python application reads the pulse counters of a S0PCM-2 or S0PCM-5 and send the total and
daily counters via MQTT to your favorite home automation like Home Assistant. The S0PCM-2 or 5 are the
S0 Pulse Counter Module sold by http://www.smartmeterdashboard.nl

Pulse vs liter vs m3
--------------------
I use the S0PCM-Reader to measure my water meter and normally in the Netherlands the water usage is
easurement in m3 and not in liters. Only this S0PCM-Reader isn't really aware of liters vs m3, be
cause it counts the pulses. So it is important for you to check how your e.g. water meter is counting
the usage, my Itron water meter send 1 pulse per liter of water. This then means the 'measuremen
t.yaml' file, which stores the total and daily counters, all should be in liters and not in m3.

The conversion from m3 to liter is easy, because you can just multiple it by 1000.
E.g. 770.123 m3 is 770123 liter.

S0PCM
-----
The following S0PCM (ascii) protocol is used by this S0PCM-Reader, a simple S0PCM telegram:

Header record (once, after start-up):
/a: S0 Pulse Counter V0.6 - 30/30/30/30/30ms

Data record (repeated every interval):
For S0PCM-5: ID:a:I:b:M1:c:d:M2:e:f:M3:g:h:M4:i:j:M5:k:l
For S0PCM-2: ID:a:I:b:M1:c:d:M2:e:f

Legenda:
a -> Unique ID of the S0PCM
b -> interval between two telegrams in seconds, this is set in the firmware at 10 seconds.
c/e/g/i/k -> number of pulses in the last interval of register 1/2/3/4/5
d/f/h/j/l/ -> number of pulses since the last start-up of register 1/2/3/4/5

Data example:
/8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
ID:8237:I:10:M1:0:0:M2:0:0:M3:0:0:M4:0:0:M5:0:0

Also the S0PCM-Reader uses the following default serialport configuration (used by S0PCM-2 and S0PCM-5):
Speed: 9600 baud
Parity: Even
Databits: 7
Stopbit: 1
Xon/Xoff: No
Rts/Cts: No

MQTT
----
MQTT Topic - when split_topic=yes (default):
base_topic/status - online/offline
base_topic/error - if any?
base_topic/1/total
base_topic/1/today
base_topic/1/yesterday
base_topic/X/total
base_topic/X/today
base_topic/X/yesterday

MQTT Topic - when split_topic=no:
base_topic/status - online/offline
base_topic/error - if any?
base_topic/1 - json string e.g. '{"total": 12345, "today": 15, "yesterday": 77}'
base_topic/X - json string e.g. '{"total": 12345, "today": 15, "yesterday": 77}'

"""

# ------------------------------------------------------------------------------------
# Threading lock
# ------------------------------------------------------------------------------------

lock = threading.Lock()

# ------------------------------------------------------------------------------------
# Global Variables
# ------------------------------------------------------------------------------------
config = {}
measurement = {}
measurementshare = {}
lasterror_serial = None
lasterror_mqtt = None
lasterrorshare = None

# Metadata
startup_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
s0pcm_firmware = "Unknown"
last_diagnostics = {}
# ------------------------------------------------------------------------------------
# Version Handling
# ------------------------------------------------------------------------------------
def GetVersion():
    # 1. Try environment variable (provided by HA addon startup)
    version = os.getenv('S0PCM_READER_VERSION')
    if version:
        return version

    # 2. Try to read from config.yaml (for local development)
    # Search in common locations relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_paths = [
        os.path.join(script_dir, '../../../config.yaml'), # Local repo structure
        os.path.join(script_dir, '../../config.yaml'),
        os.path.join(script_dir, 'config.yaml'),
        './config.yaml'
    ]

    for path in search_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    config_yaml = yaml.safe_load(f)
                    if config_yaml and 'version' in config_yaml:
                        return f"{config_yaml['version']} (local)"
            except Exception:
                pass
    
    return 'dev'

s0pcmreaderversion = GetVersion()

# ------------------------------------------------------------------------------------
# Parameters
# ------------------------------------------------------------------------------------
parser = argparse.ArgumentParser(prog='s0pcm-reader', description='S0 Pulse Counter Module', epilog='...')
parser.add_argument('-c', '--config', help='Directory where the configuration resides', type=str, default='./')
args = parser.parse_args()

configdirectory = args.config
if not configdirectory.endswith('/'):
    configdirectory += '/'

# ------------------------------------------------------------------------------------
# Setup filenames
# ------------------------------------------------------------------------------------
configname = configdirectory + 'configuration.json'
measurementname = configdirectory + 'measurement.yaml'
logname= configdirectory + 's0pcm-reader.log'

# ------------------------------------------------------------------------------------
# Error Handling
# ------------------------------------------------------------------------------------
def SetError(message, category='serial'):
    global lasterror_serial
    global lasterror_mqtt
    global lasterrorshare

    changed = False
    if category == 'serial':
        if message != lasterror_serial:
            lasterror_serial = message
            changed = True
    else:
        if message != lasterror_mqtt:
            lasterror_mqtt = message
            changed = True

    if changed:
        # Update the shared state
        errors = []
        if lasterror_serial:
            errors.append(lasterror_serial)
        if lasterror_mqtt:
            errors.append(lasterror_mqtt)
        
        new_error = " | ".join(errors) if errors else None
        
        lock.acquire()
        lasterrorshare = new_error
        lock.release()

        if message:
            logger.error(f"[{category.upper()}] {message}")
        
        # Trigger MQTT publish
        trigger.set()

# ------------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------------
logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

# ------------------------------------------------------------------------------------
# Read the 'configuration.yaml' file
# ------------------------------------------------------------------------------------
def ReadConfig():

    global config

    try:
        with open(configname, 'r') as f:
            # config = yaml.safe_load(f)
            config = json.load(f)
    except FileNotFoundError:
        print('WARN: No \'' + configname + '\' found, using defaults.')

    # Setup 'log' variables if not existing
    if not 'log' in config: config['log'] = {}
    if not 'size' in config['log']: config['log']['size'] = 10
    if not 'count' in config['log']: config['log']['count'] = 3

    if 'level' in config['log']:
        config['log']['level'] = str(config['log']['level']).upper()

        if config['log']['level'] != 'CRITICAL' and \
           config['log']['level'] != 'ERROR' and \
           config['log']['level'] != 'WARNING' and \
           config['log']['level'] != 'CRITICAL' and \
           config['log']['level'] != 'INFO' and \
           config['log']['level'] != 'DEBUG':
            print('WARN: Invalid \'level\' ' + config['log']['level'] + ' supplied. Only \'critical\', \'error\', \'warning\', \'info\' and \'debug\' are supported. Using \'warning\' now.')
            config['log']['level'] = 'WARNING'
    else:
        # Setup loglevel, default is 'warning'
        config['log']['level'] = 'WARNING'

    #  Convert MB to Bytes
    config['log']['size'] = config['log']['size'] * 1024 * 1024

    # Setup logfile and rotation
    handler = RotatingFileHandler(logname, maxBytes=config['log']['size'], backupCount=config['log']['count'])
    handler.setLevel(config['log']['level'])
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(handler)

    # Setup logging to stderr
    stream = logging.StreamHandler()
    stream.setLevel(config['log']['level'])
    stream.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(stream)

    # Setup 'mqtt' variables if not existing
    if 'mqtt' in config:
        if config['mqtt'] == None:
            config['mqtt'] = {}
    else:
        config['mqtt'] = {}
    if not 'host' in config['mqtt']: config['mqtt']['host'] = '127.0.0.1'
    if config['mqtt'].get('port') in [None, ""]: config['mqtt']['port'] = 1883
    if config['mqtt'].get('tls_port') in [None, ""]: config['mqtt']['tls_port'] = 8883
    if not 'username' in config['mqtt']: config['mqtt']['username'] = None
    if not 'password' in config['mqtt']: config['mqtt']['password'] = None
    if not 'base_topic' in config['mqtt']: config['mqtt']['base_topic'] = 's0pcmreader'
    if config['mqtt'].get('client_id') in [None, "", "None"]: config['mqtt']['client_id'] = None
    if not 'version' in config['mqtt']: config['mqtt']['version'] = mqtt.MQTTv5
    if config['mqtt'].get('retain') in [None, ""]: config['mqtt']['retain'] = True
    if config['mqtt'].get('split_topic') in [None, ""]: config['mqtt']['split_topic'] = True
    if config['mqtt'].get('connect_retry') in [None, ""]: config['mqtt']['connect_retry'] = 5
    if config['mqtt'].get('online') in [None, ""]: config['mqtt']['online'] = 'online'
    if config['mqtt'].get('offline') in [None, ""]: config['mqtt']['offline'] = 'offline'
    if config['mqtt'].get('lastwill') in [None, ""]: config['mqtt']['lastwill'] = 'offline'
    if config['mqtt'].get('discovery') in [None, ""]: config['mqtt']['discovery'] = True
    if config['mqtt'].get('discovery_prefix') in [None, ""]: config['mqtt']['discovery_prefix'] = 'homeassistant'

    if str(config['mqtt']['version']) == '3.1':
      config['mqtt']['version'] = mqtt.MQTTv31
    elif str(config['mqtt']['version']) == '3.1.1':
      config['mqtt']['version'] = mqtt.MQTTv311
    elif str(config['mqtt']['version']) == '5.0':
      config['mqtt']['version'] = mqtt.MQTTv5
    else:
      config['mqtt']['version'] = mqtt.MQTTv5
 
    # TLS configuration
    if not 'tls' in config['mqtt']: config['mqtt']['tls'] = False
    if not 'tls_ca' in config['mqtt']: config['mqtt']['tls_ca'] = ''
    if not 'tls_check_peer' in config['mqtt']: config['mqtt']['tls_check_peer'] = False

    # Append the configuration path if no '/' is in front of the CA file
    if config['mqtt']['tls_ca'] != '':
        if not config['mqtt']['tls_ca'].startswith('/'):
            config['mqtt']['tls_ca'] = configdirectory + config['mqtt']['tls_ca']

    # Setup 'serial' variables if not existing
    if 'serial' in config:
        if config['serial'] == None:
            config['serial'] = {}
    else:
        config['serial'] = {}
    if not 'port' in config['serial']: config['serial']['port'] = '/dev/ttyACM0'
    if not 'baudrate' in config['serial']: config['serial']['baudrate'] = 9600
    if not 'parity' in config['serial']: config['serial']['parity'] = serial.PARITY_EVEN
    if not 'stopbits' in config['serial']: config['serial']['stopbits'] = serial.STOPBITS_ONE
    if not 'bytesize' in config['serial']: config['serial']['bytesize'] = serial.SEVENBITS
    if not 'timeout' in config['serial']: config['serial']['timeout'] = None
    if not 'connect_retry' in config['serial']: config['serial']['connect_retry'] = 5

    # Setup 's0pcm'
    if 's0pcm' in config:
        if config['s0pcm'] == None:
            config['s0pcm'] = {}
    else:
        config['s0pcm'] = {}
    if not 'include' in config['s0pcm']: config['s0pcm']['include'] = None
    if not 'dailystat' in config['s0pcm']: config['s0pcm']['dailystat'] = None
    if not 'publish_interval' in config['s0pcm']: config['s0pcm']['publish_interval'] = None
    if not 'publish_onchange' in config['s0pcm']: config['s0pcm']['publish_onchange'] = True


    logger.info(f'Start: s0pcm-reader - version: {s0pcmreaderversion}')
    
    # Redact password from logging
    config_log = copy.deepcopy(config)
    if 'mqtt' in config_log and 'password' in config_log['mqtt'] and config_log['mqtt']['password'] is not None:
        config_log['mqtt']['password'] = '********'

    logger.debug('Config: %s', str(config_log))

# ------------------------------------------------------------------------------------
# Read the 'measurement.yaml' file
# ------------------------------------------------------------------------------------
def ReadMeasurement():

    global measurement

    try:
        with open(measurementname, 'r') as f:
            measurement = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning('No \'%s\' found, using defaults.', measurementname)

    # check if measurement is None
    if measurement is not None:
        # check date format
        if 'date' in measurement:
            # check date format
            try:
                measurement['date'] = datetime.datetime.strptime(str(measurement['date']), '%Y-%m-%d')
                measurement['date'] = measurement['date'].date()
            except ValueError:
                SetError(f"'{measurementname}' has an invalid date field '{str(measurement['date'])}', default to today '{str(datetime.date.today())}'", category='serial')
                measurement['date'] = datetime.date.today()
        else:
            measurement['date'] = datetime.date.today()

        logger.debug('Measurement: %s', str(measurement))
    else:
        logger.error('\'%s\' is empty: \'%s\' fix this by removing the file or restoring a backup if you have one...', measurementname, str(measurement))
        raise SystemExit('Cannot continue, the error above needs to be fixed first')

# ------------------------------------------------------------------------------------
# Task to read the serial port. We continue to try to open the serialport, because
# we don't want to exit with such error.
# ------------------------------------------------------------------------------------
class TaskReadSerial(threading.Thread):

    def __init__(self, trigger, stopper):
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper

        self._serialerror = 0

    def ReadSerial(self):

        global measurementshare
        global s0pcm_firmware

        while not self._stopper.is_set():

            logger.debug('Opening serialport \'%s\'', config['serial']['port'])

            try:
                ser = serial.Serial(config['serial']['port'], 
                                    baudrate=config['serial']['baudrate'],
                                    parity=config['serial']['parity'],
                                    stopbits=config['serial']['stopbits'],
                                    bytesize=config['serial']['bytesize'],
                                    timeout=config['serial']['timeout'])
                self._serialerror = 0
            except Exception as e:
                self._serialerror += 1
                SetError(f"Serialport connection failed: {type(e).__name__}: '{str(e)}'", category='serial')
                logger.error('Retry in %d seconds', config['serial']['connect_retry'])
                time.sleep(config['serial']['connect_retry'])
                continue

            # Only do a read of the data when the port is opened succesfully
            while not self._stopper.is_set():

                try:
                    datain = ser.readline()
                except Exception as e:
                    SetError(f"Serialport read error: {type(e).__name__}: '{str(e)}'", category='serial')
                    ser.close()
                    break
             
                # check if there is data received
                # If there is really nothing, most likely a timeout on reading the input data
                if len(datain) == 0:
                    SetError("Serialport read timeout: Failed to read any data", category='serial')
                    ser.close()
                    break

                # need to decode the data to ascii string
                try:
                    datastr = datain.decode('ascii')
                except UnicodeDecodeError:
                    SetError(f"Failed to decode serial data: '{str(datain)}'", category='serial')
                    continue

                # Need to remove '\r\n' from the input
                datastr = datastr.rstrip('\r\n')

                if datastr.startswith('/'):
                    logger.debug('Header Packet: \'%s\'', datastr)
                    # Example: /8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
                    try:
                        if ':' in datastr:
                            s0pcm_firmware = datastr.split(':', 1)[1].strip()
                        else:
                            s0pcm_firmware = datastr[1:].strip()
                    except Exception:
                        s0pcm_firmware = datastr
                elif datastr.startswith('ID:'):
                    logger.debug('S0PCM Packet: \'%s\'', datastr)

                    # Split data into an array
                    s0arr = datastr.split(':')

                    # s0pcm-5 - 19
                    if len(s0arr) == 19:
                        # ID:8237:I:10:M1:0:0:M2:0:0:M3:0:0:M4:0:0:M5:0:0
                        size = 5

                    # s0pcm-2 - 10
                    elif len(s0arr) == 10: 
                        # ID:8237:I:10:M1:0:0:M2:0:0
                        size = 2

                    else:
                        SetError(f"Packet has invalid length: Expected 10 or 19, got {len(s0arr)}. Packet: '{datastr}'", category='serial')
                        continue

                    # Key a copy of the measurement file, then we known we need to write the file
                    measurementstr = str(measurement)

                    # Loop through 2/5 s0pcm data
                    for count in range(1, size + 1):
                        offset = 4 + ((count - 1) * 3)
                        if s0arr[offset] == 'M' + str(count):
                            # We are interested in the total pulse count, because that is most reliable

                            try:
                                pulsecount = int(s0arr[offset + 2])
                            except:
                                SetError(f"Cannot convert pulsecount '{s0arr[offset + 2]}' into integer for meter {count}", category='serial')
                                pulsecount = 0

                            # Initialize the variables, if they doesn't exist
                            if not count in measurement: measurement[count] = {}
                            if not 'pulsecount' in measurement[count]: measurement[count]['pulsecount'] = 0
                            if not 'total' in measurement[count]: measurement[count]['total'] = 0
                            if not 'today' in measurement[count]: measurement[count]['today'] = 0
                            if not 'yesterday' in measurement[count]: measurement[count]['yesterday'] = 0
                            
                            # We got a date change
                            if str(measurement['date']) != str(datetime.date.today()):
                                logger.debug('Day changed from \'%s\' to \'%s\', resetting today counter \'%d\' to \'0\'. Yesterday counter is \'%d\'', str(measurement['date']), str(datetime.date.today()), count, measurement[count]['today'])
                                measurement[count]['yesterday'] = measurement[count]['today']
                                measurement[count]['today'] = 0

                                # Write the counters to a text file if required
                                todayfile = False
                                if config['s0pcm']['dailystat'] != None:
                                    if count in config['s0pcm']['dailystat']:
                                        todayfile = True

                                if todayfile == True:
                                    try:
                                        fstat = open(configdirectory + 'daily-' + str(count) + '.txt', 'a')
                                        fstat.write(str(measurement['date']) + ';' + str(measurement[count]['yesterday']) + '\n')
                                        fstat.close()
                                    except Exception as e:
                                        SetError(f"Stats file '{configdirectory}daily-{str(count)}.txt' write/create failed: {type(e).__name__}: '{str(e)}'", category='serial')
                            
                            if pulsecount > measurement[count]['pulsecount']:

                                logger.debug('Pulsecount changed from \'%d\' to \'%d\'', measurement[count]['pulsecount'], pulsecount)

                                # Pulsecount has changed, lets do some magic :-)
                                delta = pulsecount - measurement[count]['pulsecount']
                                measurement[count]['pulsecount'] = pulsecount
                                measurement[count]['total'] += delta
                                measurement[count]['today'] += delta

                            elif pulsecount < measurement[count]['pulsecount']:
                                SetError(f"Pulsecount anomaly detected for meter {count}: Stored pulsecount '{measurement[count]['pulsecount']}' is higher than read '{pulsecount}'. This normally happens if S0PCM is restarted.", category='serial')
                                delta = pulsecount
                                measurement[count]['pulsecount'] = pulsecount
                                measurement[count]['total'] += delta
                                measurement[count]['today'] += delta

                        else:
                            SetError(f"Expecting 'M{str(count)}', received '{s0arr[offset]}'", category='serial')
                            continue

                    # Update todays date - but we don't convert to str yet, it looks nicer without it in the yaml file ;-)
                    if str(measurement['date']) != str(datetime.date.today()):
                        measurement['date'] = datetime.date.today()

                    # We reached this point, so we have a valid packet
                    SetError(None, category='serial')

                    # Write the 'measurement.yaml' file with the new data. Only when data has changed.
                    if measurementstr == str(measurement):
                        logger.debug('No change to the \'%s\' file (no write)', measurementname)
                    else:
                        logger.debug('Updated \'%s\' file', measurementname)
                        with open(measurementname, 'w') as f:
                            yaml.dump(measurement, f, default_flow_style=False)

                    # Do some lock/release on global variables
                    lock.acquire()
                    measurementshare = copy.deepcopy(measurement)
                    lock.release()

                    # Trigger that new data is available for MQTT
                    self._trigger.set()

                elif datastr == '':
                    logger.warning('Empty Packet received, this can happen during start-up')
                else:
                    SetError(f"Invalid Packet: '{datastr}'", category='serial')

    def run(self):
        try:
            self.ReadSerial()
        except:
            logger.error('Fatal exception has occured', exc_info=True)
        finally:
            self._stopper.set()

# ------------------------------------------------------------------------------------
# Task to do MQTT Publish
# ------------------------------------------------------------------------------------

class TaskDoMQTT(threading.Thread):

    def __init__(self, trigger, stopper):
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._connected = False
        self._discovery_sent = False

    def on_connect(self, mqttc, obj, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            self._discovery_sent = False
            logger.debug('MQTT successfully connected to broker')
            self._trigger.set()
            self._mqttc.publish(config['mqtt']['base_topic'] + '/status', config['mqtt']['online'], retain=config['mqtt']['retain'])
            
            # Subscribe to 'set' commands
            topic_set = config['mqtt']['base_topic'] + '/+/total/set'
            self._mqttc.subscribe(topic_set)
            logger.debug('Subscribed to: ' + topic_set)
        else:
            self._connected = False
            SetError(f"MQTT failed to connect to broker: {mqtt.connack_string(reason_code)}", category='mqtt')

    def on_disconnect(self, mqttc, obj, flags, reason_code, properties):
        self._connected = False
        if reason_code == 0:
            logger.debug('MQTT successfully disconnected from broker')
        else:
            SetError(f"MQTT failed to disconnect from broker: {mqtt.connack_string(reason_code)}", category='mqtt')
            logger.error(f"MQTT disconnected unexpectedly. Reason: {reason_code} ({mqtt.connack_string(reason_code)})")

    def on_message(self, mqttc, obj, msg):
        global measurementshare
        logger.debug('MQTT on_message: ' + msg.topic + ' ' + str(msg.qos) + ' ' + str(msg.payload))

        # Check for set command
        if msg.topic.endswith('/total/set'):
            try:
                # Topic format: base_topic/ID/total/set
                parts = msg.topic.split('/')
                # parts[-1] = 'set', parts[-2] = 'total', parts[-3] = ID
                meter_id_str = parts[-3]
                
                try:
                    meter_id = int(meter_id_str)
                except ValueError:
                    SetError(f"Ignored set command for non-integer meter ID: {meter_id_str}", category='mqtt')
                    return

                payload_str = msg.payload.decode('utf-8')
                try:
                    # Support int or float input, but store as likely int or float
                    # Since original pulses are ints, we cast to float then int? 
                    # If user provides 123.45, we probably should store 123.45 if we want to be exact?
                    # But the script generally deals with pulses.
                    # Let's verify what the script does.
                    # It reads INT from serial: pulsecount = int(s0arr[offset + 2])
                    # So the meters count int pulses.
                    # If we set total, we are setting the "Pulse Count Total" theoretically?
                    # But 'total' in measurement is usually derived from pulses.
                    # NOTE: If we set 'total' to 1000. And pulsecount comes in. 
                    # The script adds DELTA of PULSES to TOTAL.
                    # So 'total' doesn't HAVE to be int, but it makes sense.
                    # Let's stick to int to match serial behavior, or float if user really wants.
                    # Given the "s0 pulse counter" nature, int is safer.
                    new_total = int(float(payload_str))
                except ValueError:
                    SetError(f"Ignored invalid payload for set command on meter {meter_id}: {payload_str}", category='mqtt')
                    return

                logger.info(f"Received MQTT set command for meter {meter_id}. Setting total to {new_total}.")

                lock.acquire()
                try:
                    if meter_id not in measurement:
                        measurement[meter_id] = {}
                        # Init default fields to prevent key errors
                        measurement[meter_id]['pulsecount'] = 0
                        measurement[meter_id]['today'] = 0
                        measurement[meter_id]['yesterday'] = 0

                    measurement[meter_id]['total'] = new_total
                    
                    # Persist immediately
                    with open(measurementname, 'w') as f:
                        yaml.dump(measurement, f, default_flow_style=False)
                    logger.debug(f"Updated measurement.yaml with new total for meter {meter_id}")

                    # Update share and trigger publish
                    measurementshare = copy.deepcopy(measurement)
                    self._trigger.set()

                finally:
                    lock.release()

            except Exception as e:
                SetError(f"Failed to process MQTT set command: {e}", category='mqtt')

    def on_publish(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_publish: mid: ' + str(mid))

    def on_subscribe(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_subscribe: ' + str(mid) + ' ' + str(reason_codes))

    def on_log(self, mqttc, obj, level, string):
        logger.debug('MQTT on_log: ' + string)

    def send_discovery(self, measurementlocal):

        if not config['mqtt']['discovery']:
            return

        if not measurementlocal:
            return

        logger.debug('Sending MQTT discovery messages')

        identifier = config['mqtt']['base_topic']
        device_info = {
            "identifiers": [identifier],
            "name": "S0PCM Reader",
            "model": "S0PCM",
            "manufacturer": "SmartMeterDashboard",
            "sw_version": s0pcmreaderversion
        }

        # Status Binary Sensor Discovery
        status_unique_id = f"s0pcm_{identifier}_status"
        status_topic = f"{config['mqtt']['discovery_prefix']}/binary_sensor/{identifier}/{status_unique_id}/config"
        logger.debug('MQTT discovery topic (status): ' + status_topic)

        # First, clear any existing retained discovery message to force HA to re-register
        self._mqttc.publish(status_topic, "", retain=True)
        
        status_payload = {
            "name": "S0PCM Reader Status",
            "unique_id": status_unique_id,
            "device": device_info,
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "state_topic": config['mqtt']['base_topic'] + '/status',
            "payload_on": config['mqtt']['online'],
            "payload_off": config['mqtt']['offline']
        }
        self._mqttc.publish(status_topic, json.dumps(status_payload), retain=config['mqtt']['retain'])

        # Cleanup legacy discovery topics
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_info/config", "", retain=config['mqtt']['retain'])
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_info_diag/config", "", retain=config['mqtt']['retain'])
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_uptime/config", "", retain=config['mqtt']['retain'])

        # Error Sensor Discovery
        error_unique_id = f"s0pcm_{identifier}_error"
        error_topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{error_unique_id}/config"
        logger.debug('MQTT discovery topic (error): ' + error_topic)

        error_payload = {
            "name": "S0PCM Reader Error",
            "unique_id": error_unique_id,
            "device": device_info,
            "entity_category": "diagnostic",
            "state_topic": config['mqtt']['base_topic'] + '/error',
            "icon": "mdi:alert-circle"
        }
        self._mqttc.publish(error_topic, json.dumps(error_payload), retain=config['mqtt']['retain'])

        # Diagnostic Sensors Discovery
        diagnostics = [
            {"id": "version", "name": "Addon Version", "icon": "mdi:information-outline"},
            {"id": "firmware", "name": "S0PCM Firmware", "icon": "mdi:chip"},
            {"id": "startup_time", "name": "Startup Time", "icon": "mdi:clock-outline", "class": "timestamp"},
            {"id": "port", "name": "Serial Port", "icon": "mdi:serial-port"}
        ]

        for diag in diagnostics:
            diag_unique_id = f"s0pcm_{identifier}_{diag['id']}"
            diag_topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{diag_unique_id}/config"
            
            diag_payload = {
                "name": f"S0PCM Reader {diag['name']}",
                "unique_id": diag_unique_id,
                "device": device_info,
                "entity_category": "diagnostic",
                "state_topic": config['mqtt']['base_topic'] + '/' + diag['id'],
                "value_template": "{{ value }}",
                "force_update": True,
                "icon": diag['icon']
            }
            if "unit" in diag: diag_payload["unit_of_measurement"] = diag["unit"]
            if "class" in diag: diag_payload["device_class"] = diag["class"]
            
            self._mqttc.publish(diag_topic, json.dumps(diag_payload), retain=config['mqtt']['retain'])

        for key in measurementlocal:
            if isinstance(key, int):

                try:
                    if not measurement[key]['enabled']:
                        continue
                except:
                    pass

                # Skip an input if not configured
                if config['s0pcm']['include'] != None:
                    if not key in config['s0pcm']['include']:
                        continue

                try:
                    instancename = measurementlocal[key]['name']
                except:
                    instancename = str(key)

                for subkey in ['total', 'today', 'yesterday']:

                    unique_id = f"s0pcm_{identifier}_{key}_{subkey}"
                    
                    # Discovery Topic
                    topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{unique_id}/config"
                    logger.debug('MQTT discovery topic: ' + topic)

                    payload = {
                        "name": f"{instancename} {subkey.capitalize()}",
                        "unique_id": unique_id,
                        "device": device_info
                    }

                    if subkey == 'total':
                        payload['state_class'] = 'total_increasing'
                    elif subkey == 'today':
                        payload['state_class'] = 'total_increasing'
                    else:
                        payload['state_class'] = 'measurement'

                    if config['mqtt']['split_topic'] == True:
                        payload['state_topic'] = config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey
                    else:
                        payload['state_topic'] = config['mqtt']['base_topic'] + '/' + instancename
                        payload['value_template'] = f"{{{{ value_json.{subkey} }}}}"

                    self._mqttc.publish(topic, json.dumps(payload), retain=config['mqtt']['retain'])

        self._discovery_sent = True
        logger.info('Sent MQTT discovery messages')

    def _setup_mqtt_client(self, use_tls):
        # Define our MQTT Client
        self._mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config['mqtt']['client_id'], protocol=config['mqtt']['version'])
        self._mqttc.on_connect = self.on_connect
        self._mqttc.on_disconnect = self.on_disconnect
        self._mqttc.on_message = self.on_message
        #self._mqttc.on_publish = self.on_publish
        #self._mqttc.on_subscribe = self.on_subscribe

        # https://github.com/eclipse/paho.mqtt.python/blob/master/examples/client_pub-wait.py

        if config['mqtt']['username'] != None:
            self._mqttc.username_pw_set(config['mqtt']['username'], config['mqtt']['password'])

        # Setup TLS if requested
        if use_tls:
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            except AttributeError:
                # Fallback for older Python versions
                context = ssl.SSLContext(ssl.PROTOCOL_TLS)

            if config['mqtt']['tls_ca'] == '':
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            else:
                if config['mqtt']['tls_check_peer']:
                    context.verify_mode = ssl.CERT_REQUIRED
                    context.check_hostname = True
                else:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                
                try:
                    context.load_verify_locations(cafile=config['mqtt']['tls_ca'])
                except Exception as e:
                    SetError(f"Failed to load TLS CA file '{config['mqtt']['tls_ca']}': {str(e)}", category='mqtt')
                    return False

            self._mqttc.tls_set_context(context=context)

        # Set last will
        self._mqttc.will_set(config['mqtt']['base_topic'] + '/status', config['mqtt']['lastwill'], retain=config['mqtt']['retain'])
        return True

    def DoMQTT(self):

        global measurementshare
        measurementprevious = {}

        # Copy the measurements to previous one, preventing send values when on change is enabled
        measurementprevious = measurement

        use_tls = config['mqtt']['tls']
        fallback_happened = False

        while not self._stopper.is_set():

            if not self._setup_mqtt_client(use_tls):
                SetError(f"Failed to setup MQTT client, retrying in {config['mqtt']['connect_retry']} seconds", category='mqtt')
                time.sleep(config['mqtt']['connect_retry'])
                continue

            # Handle automatic port swapping (configured plain port vs configured TLS port)
            plain_port = int(config['mqtt']['port'])
            tls_port = int(config['mqtt']['tls_port'])
            
            if use_tls:
                current_port = tls_port
            else:
                current_port = plain_port

            logger.debug('Connecting to MQTT Broker \'%s:%s\' (TLS: %s)', config['mqtt']['host'], str(current_port), str(use_tls))

            try:
                self._mqttc.connect(config['mqtt']['host'], current_port, 60)
            except (ssl.SSLError, ssl.CertificateError, ConnectionResetError) as e:
                if use_tls and not fallback_happened:
                    SetError(f"MQTT TLS connection failed: {type(e).__name__}: '{str(e)}'. Falling back to plain MQTT.", category='mqtt')
                    use_tls = False
                    fallback_happened = True
                    continue
                else:
                    SetError(f"MQTT connection failed: {type(e).__name__}: '{str(e)}'", category='mqtt')
                    logger.error('Retry in %d seconds', config['mqtt']['connect_retry'])
                    time.sleep(config['mqtt']['connect_retry'])
                    continue
            except Exception as e:
                SetError(f"MQTT connection failed: {type(e).__name__}: '{str(e)}'", category='mqtt')
                logger.error('Retry in %d seconds', config['mqtt']['connect_retry'])
                time.sleep(config['mqtt']['connect_retry'])
                continue

            #connect_async(host, port=1883, keepalive=60, bind_address="")
            self._mqttc.loop_start()

            # Let's wait 1 second, otherwise we can be too fast?
            time.sleep(1)

            while not self._stopper.is_set():
                # Do some lock/release on global variables
                lock.acquire()
                measurementlocal = copy.deepcopy(measurementshare)
                errorlocal = lasterrorshare
                lock.release()

                # Check if we are connected
                if self._connected == False:
                    logger.debug('Not connected to MQTT Broker, waiting...')
                    # Wait for a change or the connect retry interval
                    self._trigger.wait(timeout=config['mqtt']['connect_retry'])
                    self._trigger.clear()
                    continue

                if not self._discovery_sent:
                    self.send_discovery(measurementlocal)

                # Publish current error state
                try:
                    error_payload = errorlocal if errorlocal else "No Error"
                    self._mqttc.publish(config['mqtt']['base_topic'] + '/error', error_payload, retain=config['mqtt']['retain'])
                except Exception as e:
                    logger.error(f"Failed to publish error state to MQTT: {e}")

                # Publish info state (once on startup, then on change)
                try:
                    bt = config['mqtt']['base_topic']
                    rt = config['mqtt']['retain']
                    
                    current_diagnostics = {
                        'version': s0pcmreaderversion,
                        'firmware': s0pcm_firmware,
                        'startup_time': startup_time,
                        'port': config['serial']['port']
                    }

                    global last_diagnostics
                    for key, val in current_diagnostics.items():
                        if key not in last_diagnostics or last_diagnostics[key] != val:
                            topic = bt + '/' + key
                            self._mqttc.publish(topic, str(val), retain=rt)
                            last_diagnostics[key] = val
                    
                    # Also keep the /info JSON for backward compatibility
                    info_payload = {
                        "version": s0pcmreaderversion,
                        "s0pcm_firmware": s0pcm_firmware,
                        "startup_time": startup_time,
                        "serial_port": config['serial']['port']
                    }
                    self._mqttc.publish(bt + '/info', json.dumps(info_payload), retain=rt)
                except Exception as e:
                    logger.error(f"Failed to publish info state to MQTT: {e}")

                for key in measurementlocal:
                    if isinstance(key, int):

                        # define dict for json value
                        jsondata = {}

                        try:
                            if not measurement[key]['enabled']:
                                continue
                        except:
                            pass

                        # Skip an input if not configured
                        if config['s0pcm']['include'] != None:
                            if not key in config['s0pcm']['include']:
                                logger.debug('MQTT Publish for input \'%d\' is disabled', key)
                                continue

                        try:
                            instancename = measurementlocal[key]['name']
                        except:
                            instancename = str(key)

                        for subkey in ['total', 'today', 'yesterday']:

                            # Try to assign the previous value, if this fails, we set it "-1" then it should always be different
                            try:
                                value_previous = measurementprevious[key][subkey]
                            except:
                                value_previous = -1

                            try:
                                if subkey in measurementlocal[key]:

                                    if config['mqtt']['split_topic'] == True:
                                        # Check if the value not changed and publish on change is off
                                        if measurementlocal[key][subkey] == value_previous and config['s0pcm']['publish_onchange'] == True:
                                            continue

                                        logger.debug('MQTT Publish of topic \'%s\' and value \'%s\'',config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey, str(measurementlocal[key][subkey]))

                                        # Do a MQTT Publish
                                        self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey, measurementlocal[key][subkey], retain=config['mqtt']['retain'])
                                    else:
                                        jsondata[subkey] = measurementlocal[key][subkey]

                            except Exception as e:
                                SetError(f"MQTT Publish Failed for {instancename}/{subkey}. {type(e).__name__}: '{str(e)}'", category='mqtt')

                        # We should publish the json value
                        if config['mqtt']['split_topic'] == False:
                            try:
                                logger.debug('MQTT Publish of topic \'%s\' and value \'%s\'',config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata))

                                # Do a MQTT Publish
                                self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata), retain=config['mqtt']['retain'])
                            except Exception as e:
                                SetError(f"MQTT Publish Failed for {instancename} (JSON). {type(e).__name__}: '{str(e)}'", category='mqtt')

                # Publish current error state
                error_published = False
                try:
                    error_payload = errorlocal if errorlocal else "No Error"
                    self._mqttc.publish(config['mqtt']['base_topic'] + '/error', error_payload, retain=config['mqtt']['retain'])
                    error_published = True
                except Exception as e:
                    SetError(f"MQTT Publish Failed for error topic. {type(e).__name__}: '{str(e)}'", category='mqtt')

                if self._connected and error_published:
                    # Clear MQTT errors (connection, commands, previous publish failures)
                    # We do this here in the loop to ensure they are published at least once after resolution.
                    SetError(None, category='mqtt')

                # Lets make also a copy of this one, then we can compare if there is a delta
                measurementprevious = copy.deepcopy(measurementlocal)

                # Now wait for the next event or interval
                if config['s0pcm']['publish_interval'] == None:
                    # Reactive mode: wait indefinitely for a trigger
                    self._trigger.wait()
                else:
                    # Periodic mode: wait for trigger or interval timeout
                    self._trigger.wait(timeout=config['s0pcm']['publish_interval'])
                
                self._trigger.clear()

            self._mqttc.loop_stop()

            # Send an official offline message
            if self._connected:
                self._mqttc.publish(config['mqtt']['base_topic'] + '/status', config['mqtt']['offline'], retain=config['mqtt']['retain'])

            self._mqttc.disconnect()

    def run(self):
        try:
            self.DoMQTT()
        except:
            logger.error('Fatal exception has occured', exc_info=True)
        finally:
            self._stopper.set()

# ------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------

try:
    ReadConfig()
    ReadMeasurement()
    measurementshare = copy.deepcopy(measurement)
except:
    logger.error('Fatal exception has occured', exc_info=True)
    # we need to quit, because we detected an error
    exit(1)

trigger = threading.Event()
stopper = threading.Event()

# Start our SerialPort thread
t1 = TaskReadSerial(trigger, stopper)
t1.start()

# Start our MQTT thread
t2 = TaskDoMQTT(trigger, stopper)
t2.start()

# Now wait until both tasks are finished
t1.join()
t2.join()

logger.info('Stop: s0pcm-reader')

# End
