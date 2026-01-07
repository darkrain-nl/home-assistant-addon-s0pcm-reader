
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
import sys
import signal

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
base_topic/X/total/set - write new total to meter X

MQTT Diagnostics:
base_topic/version
base_topic/firmware
base_topic/startup_time
base_topic/port
base_topic/info - json string with all diagnostic info

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
def SetError(message, category='serial', trigger_event=True):
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
        
        if trigger_event:
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
# Custom Rotating File Handler to log rotation events
# ------------------------------------------------------------------------------------
class DetailedRotatingFileHandler(RotatingFileHandler):
    def doRollover(self):
        try:
            # Manually format timestamp to match logging format
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
            
            # Log that rotation is starting in the OLD file (write directly to stream)
            if self.stream:
                self.stream.write(f"{now} INFO: --- Log Rotation Started ---\n")
                self.stream.flush()

            # Perform the actual rotation
            super().doRollover()

            # Log that a new file has started in the NEW file (write directly to stream)
            if self.stream:
                self.stream.write(f"{now} INFO: --- New Log File Started ---\n")
                self.stream.flush()
        except Exception:
            # Fallback to standard rollover if manual write fails
            super().doRollover()

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
        print(f"WARN: No '{configname}' found, using defaults.")

    # Setup 'log' variables
    config.setdefault('log', {})
    config['log'].setdefault('size', 5)
    config['log'].setdefault('count', 3)
    
    # Handle log level
    if 'level' in config['log']:
        config['log']['level'] = str(config['log']['level']).upper()
        valid_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
        if config['log']['level'] not in valid_levels:
            print(f"WARN: Invalid 'level' {config['log']['level']} supplied. Using 'WARNING'.")
            config['log']['level'] = 'WARNING'
    else:
        config['log']['level'] = 'WARNING'

    # Convert MB to Bytes
    config['log']['size'] = config['log']['size'] * 1024 * 1024

    # Setup logfile and rotation
    handler = DetailedRotatingFileHandler(logname, maxBytes=config['log']['size'], backupCount=config['log']['count'])
    handler.setLevel(config['log']['level'])
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(handler)

    # Setup logging to stderr
    stream = logging.StreamHandler()
    stream.setLevel(config['log']['level'])
    stream.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(stream)

    # Setup 'mqtt' variables
    config.setdefault('mqtt', {})
    if config['mqtt'] is None: config['mqtt'] = {}

    config['mqtt'].setdefault('host', '127.0.0.1')
    if config['mqtt'].get('port') in [None, ""]: config['mqtt']['port'] = 1883
    if config['mqtt'].get('tls_port') in [None, ""]: config['mqtt']['tls_port'] = 8883
    config['mqtt'].setdefault('username', None)
    config['mqtt'].setdefault('password', None)
    config['mqtt'].setdefault('base_topic', 's0pcmreader')
    if config['mqtt'].get('client_id') in [None, "", "None"]: config['mqtt']['client_id'] = None
    config['mqtt'].setdefault('version', mqtt.MQTTv5)
    if config['mqtt'].get('retain') in [None, ""]: config['mqtt']['retain'] = True
    if config['mqtt'].get('split_topic') in [None, ""]: config['mqtt']['split_topic'] = True
    if config['mqtt'].get('connect_retry') in [None, ""]: config['mqtt']['connect_retry'] = 5
    if config['mqtt'].get('online') in [None, ""]: config['mqtt']['online'] = 'online'
    if config['mqtt'].get('offline') in [None, ""]: config['mqtt']['offline'] = 'offline'
    if config['mqtt'].get('lastwill') in [None, ""]: config['mqtt']['lastwill'] = 'offline'
    if config['mqtt'].get('discovery') in [None, ""]: config['mqtt']['discovery'] = True
    if config['mqtt'].get('discovery_prefix') in [None, ""]: config['mqtt']['discovery_prefix'] = 'homeassistant'

    # Map version strings to constants
    version_str = str(config['mqtt']['version'])
    if version_str == '3.1':
        config['mqtt']['version'] = mqtt.MQTTv31
    elif version_str == '3.1.1':
        config['mqtt']['version'] = mqtt.MQTTv311
    else: # Default or 5.0
        config['mqtt']['version'] = mqtt.MQTTv5
 
    # TLS configuration
    config['mqtt'].setdefault('tls', False)
    config['mqtt'].setdefault('tls_ca', '')
    config['mqtt'].setdefault('tls_check_peer', False)

    # Append the configuration path if no '/' is in front of the CA file
    if config['mqtt']['tls_ca'] != '' and not config['mqtt']['tls_ca'].startswith('/'):
        config['mqtt']['tls_ca'] = configdirectory + config['mqtt']['tls_ca']

    # Setup 'serial' variables
    config.setdefault('serial', {})
    if config['serial'] is None: config['serial'] = {}

    config['serial'].setdefault('port', '/dev/ttyACM0')
    config['serial'].setdefault('baudrate', 9600)
    config['serial'].setdefault('parity', serial.PARITY_EVEN)
    config['serial'].setdefault('stopbits', serial.STOPBITS_ONE)
    config['serial'].setdefault('bytesize', serial.SEVENBITS)
    config['serial'].setdefault('timeout', None)
    config['serial'].setdefault('connect_retry', 5)

    # Setup 's0pcm'
    config.setdefault('s0pcm', {})
    if config['s0pcm'] is None: config['s0pcm'] = {}

    config['s0pcm'].setdefault('include', None)
    config['s0pcm'].setdefault('dailystat', None)
    config['s0pcm'].setdefault('publish_interval', None)
    config['s0pcm'].setdefault('publish_onchange', True)

    logger.info(f'Start: s0pcm-reader - version: {s0pcmreaderversion}')
    
    # Redact password from logging
    config_log = copy.deepcopy(config)
    if config_log.get('mqtt') and config_log['mqtt'].get('password'):
        config_log['mqtt']['password'] = '********'

    logger.debug(f'Config: {str(config_log)}')

# ------------------------------------------------------------------------------------
# Read the 'measurement.yaml' file
# ------------------------------------------------------------------------------------
def ReadMeasurement():

    global measurement

    try:
        with open(measurementname, 'r') as f:
            data = yaml.safe_load(f)
            # Handle empty file (None) or valid content
            measurement = data if data is not None else {}
    except FileNotFoundError:
        logger.warning(f"No '{measurementname}' found, using defaults.")
        measurement = {}
    except Exception as e:
         logger.error(f"Failed to read '{measurementname}': {e}. Using defaults.")
         measurement = {}

    if not isinstance(measurement, dict):
        logger.error(f"'{measurementname}' content is not a dictionary ({type(measurement)}). Using defaults.")
        measurement = {}

    # Handle Date
    saved_date = measurement.get('date')
    if saved_date:
        try:
            # Handle both string 'YYYY-MM-DD' and existing date objects
            if isinstance(saved_date, str):
                measurement['date'] = datetime.datetime.strptime(saved_date, '%Y-%m-%d').date()
            elif isinstance(saved_date, datetime.date):
                pass # Already a date object (yaml might parse it automatically)
            elif isinstance(saved_date, datetime.datetime):
                measurement['date'] = saved_date.date()
            else:
                # Try casting to string as a fallback for other types
                measurement['date'] = datetime.datetime.strptime(str(saved_date), '%Y-%m-%d').date()
        except ValueError:
            SetError(f"'{measurementname}' has an invalid date field '{saved_date}', defaulting to today.", category='serial')
            measurement['date'] = datetime.date.today()
    else:
        measurement['date'] = datetime.date.today()

    logger.debug(f"Measurement: {str(measurement)}")

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

    def _connect(self):
        """Argument-less method to connect to serial port with retry logic."""
        while not self._stopper.is_set():
            logger.debug(f"Opening serialport '{config['serial']['port']}'")
            try:
                ser = serial.Serial(config['serial']['port'], 
                                    baudrate=config['serial']['baudrate'],
                                    parity=config['serial']['parity'],
                                    stopbits=config['serial']['stopbits'],
                                    bytesize=config['serial']['bytesize'],
                                    timeout=config['serial']['timeout'])
                self._serialerror = 0
                return ser
            except Exception as e:
                self._serialerror += 1
                SetError(f"Serialport connection failed: {type(e).__name__}: '{str(e)}'", category='serial')
                logger.error(f"Retry in {config['serial']['connect_retry']} seconds")
                time.sleep(config['serial']['connect_retry'])
        return None

    def _handle_header(self, datastr):
        """Parse header packet to extract firmware version."""
        global s0pcm_firmware
        logger.debug(f"Header Packet: '{datastr}'")
        # Example: /8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
        try:
            if ':' in datastr:
                s0pcm_firmware = datastr.split(':', 1)[1].strip()
            else:
                s0pcm_firmware = datastr[1:].strip()
        except Exception:
            s0pcm_firmware = datastr

    def _handle_data_packet(self, datastr):
        """Parse data packet and update measurements."""
        global measurementshare
        
        logger.debug(f"S0PCM Packet: '{datastr}'")

        # Split data into an array
        s0arr = datastr.split(':')
        size = 0

        # s0pcm-5 (19 parts) or s0pcm-2 (10 parts)
        if len(s0arr) == 19:
            size = 5
        elif len(s0arr) == 10:
            size = 2
        else:
            SetError(f"Packet has invalid length: Expected 10 or 19, got {len(s0arr)}. Packet: '{datastr}'", category='serial')
            return

        # Keep a copy to check for changes later
        measurementstr = str(measurement)

        # Loop through 2/5 s0pcm data
        for count in range(1, size + 1):
            offset = 4 + ((count - 1) * 3)
            
            # expected format: M1:x:x
            if s0arr[offset] != 'M' + str(count):
                SetError(f"Expecting 'M{str(count)}', received '{s0arr[offset]}'", category='serial')
                continue

            try:
                pulsecount = int(s0arr[offset + 2])
            except ValueError:
                SetError(f"Cannot convert pulsecount '{s0arr[offset + 2]}' into integer for meter {count}", category='serial')
                pulsecount = 0

            self._update_meter(count, pulsecount)

        # Update todays date if needed
        if str(measurement['date']) != str(datetime.date.today()):
            measurement['date'] = datetime.date.today()

        # Valid packet processed
        SetError(None, category='serial')

        # Persist if changed
        if measurementstr == str(measurement):
            logger.debug(f"No change to the '{measurementname}' file (no write)")
        else:
            logger.debug(f"Updated '{measurementname}' file")
            with open(measurementname, 'w') as f:
                yaml.dump(measurement, f, default_flow_style=False)

        # Update shared state
        lock.acquire()
        measurementshare = copy.deepcopy(measurement)
        lock.release()

        # Signal new data
        self._trigger.set()

    def _update_meter(self, count, pulsecount):
        """Update logic for a single meter."""
        # Initialize if missing
        if count not in measurement: measurement[count] = {}
        if 'pulsecount' not in measurement[count]: measurement[count]['pulsecount'] = 0
        if 'total' not in measurement[count]: measurement[count]['total'] = 0
        if 'today' not in measurement[count]: measurement[count]['today'] = 0
        if 'yesterday' not in measurement[count]: measurement[count]['yesterday'] = 0
        
        # Check date change
        if str(measurement['date']) != str(datetime.date.today()):
            logger.debug(f"Day changed from '{str(measurement['date'])}' to '{str(datetime.date.today())}', resetting today counter '{count}' to '0'. Yesterday counter is '{measurement[count]['today']}'")
            measurement[count]['yesterday'] = measurement[count]['today']
            measurement[count]['today'] = 0

            # Write daily stats
            if config['s0pcm']['dailystat'] is not None and count in config['s0pcm']['dailystat']:
                try:
                    with open(configdirectory + 'daily-' + str(count) + '.txt', 'a') as fstat:
                        fstat.write(str(measurement['date']) + ';' + str(measurement[count]['yesterday']) + '\n')
                except Exception as e:
                    SetError(f"Stats file '{configdirectory}daily-{str(count)}.txt' write/create failed: {type(e).__name__}: '{str(e)}'", category='serial')

        # Calculate delta
        if pulsecount > measurement[count]['pulsecount']:
            logger.debug(f"Pulsecount changed from '{measurement[count]['pulsecount']}' to '{pulsecount}'")
            delta = pulsecount - measurement[count]['pulsecount']
            measurement[count]['pulsecount'] = pulsecount
            measurement[count]['total'] += delta
            measurement[count]['today'] += delta

        elif pulsecount < measurement[count]['pulsecount']:
            # Pulsecount reset (e.g. device restart)
            SetError(f"Pulsecount anomaly detected for meter {count}: Stored pulsecount '{measurement[count]['pulsecount']}' is higher than read '{pulsecount}'. This normally happens if S0PCM is restarted.", category='serial')
            delta = pulsecount
            measurement[count]['pulsecount'] = pulsecount
            measurement[count]['total'] += delta
            measurement[count]['today'] += delta

    def _read_loop(self, ser):
        """Read loop using the connected serial object."""
        while not self._stopper.is_set():
            try:
                datain = ser.readline()
            except Exception as e:
                SetError(f"Serialport read error: {type(e).__name__}: '{str(e)}'", category='serial')
                break # Break to reconnect
            
            if len(datain) == 0:
                # Timeout
                # SetError("Serialport read timeout: Failed to read any data", category='serial')
                # Actually, a timeout might just mean silence. But if we expect periodic data...
                # The original code treated 0 length as an error and reconnected.
                SetError("Serialport read timeout: Failed to read any data", category='serial')
                break

            try:
                datastr = datain.decode('ascii').rstrip('\r\n')
            except UnicodeDecodeError:
                SetError(f"Failed to decode serial data: '{str(datain)}'", category='serial')
                continue

            if datastr.startswith('/'):
                self._handle_header(datastr)
            elif datastr.startswith('ID:'):
                self._handle_data_packet(datastr)
            elif datastr == '':
                logger.warning('Empty Packet received, this can happen during start-up')
            else:
                SetError(f"Invalid Packet: '{datastr}'", category='serial')

    def run(self):
        try:
            while not self._stopper.is_set():
                ser = self._connect()
                if ser:
                    self._read_loop(ser)
                    ser.close()
        except Exception:
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
        self._mqttc = None
        self._last_diagnostics = {}

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
        logger.debug('MQTT on_message: ' + msg.topic + ' ' + str(msg.qos) + ' ' + str(msg.payload))

        # Check for set command
        if msg.topic.endswith('/total/set'):
            self._handle_set_command(msg)

    def _handle_set_command(self, msg):
        global measurementshare
        try:
            # Topic format: base_topic/ID_or_NAME/total/set
            parts = msg.topic.split('/')
            identifier = parts[-3]
            meter_id = None
            
            try:
                meter_id = int(identifier)
            except ValueError:
                # If not an integer, try to find a meter with a matching name (case-insensitive)
                for key, data in measurement.items():
                    if isinstance(key, int):
                        name = data.get('name')
                        if name and name.lower() == identifier.lower():
                            meter_id = key
                            break
            
            if meter_id is None:
                SetError(f"Ignored set command for unknown meter ID or Name: {identifier}", category='mqtt')
                return

            payload_str = msg.payload.decode('utf-8')
            try:
                # Support int or float input, but store as likely int
                new_total = int(float(payload_str))
            except ValueError:
                SetError(f"Ignored invalid payload for set command on meter {meter_id}: {payload_str}", category='mqtt')
                return

            logger.info(f"Received MQTT set command for meter {meter_id}. Setting total to {new_total}.")

            with lock:
                if meter_id not in measurement:
                    measurement[meter_id] = {}
                    measurement[meter_id].setdefault('pulsecount', 0)
                    measurement[meter_id].setdefault('today', 0)
                    measurement[meter_id].setdefault('yesterday', 0)

                measurement[meter_id]['total'] = new_total
                
                # Persist immediately
                with open(measurementname, 'w') as f:
                    yaml.dump(measurement, f, default_flow_style=False)
                logger.debug(f"Updated measurement.yaml with new total for meter {meter_id}")

                # Update share and trigger publish
                measurementshare = copy.deepcopy(measurement)
                self._trigger.set()

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
        self._mqttc.publish(status_topic, json.dumps(status_payload), retain=True)

        # Cleanup legacy discovery topics
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_info/config", "", retain=True)
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_info_diag/config", "", retain=True)
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_uptime/config", "", retain=True)

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
        self._mqttc.publish(error_topic, json.dumps(error_payload), retain=True)

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
            
            self._mqttc.publish(diag_topic, json.dumps(diag_payload), retain=True)

        for key in measurementlocal:
            if isinstance(key, int):
                # Cleanup: Purge any orphaned "Meter ID" sensors from previous versions
                # HA removes entities when their discovery topic is empty
                id_unique_id = f"s0pcm_{identifier}_{key}_id"
                id_purge_topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{id_unique_id}/config"
                self._mqttc.publish(id_purge_topic, "", retain=True)

                if config['s0pcm']['include'] is not None and key not in config['s0pcm']['include']:
                    continue

                # Check if enabled
                if not measurement[key].get('enabled', True):
                     continue

                instancename = measurementlocal[key].get('name', str(key))

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

                    # Publish discovery
                    self._mqttc.publish(topic, json.dumps(payload), retain=True)



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

    def _connect_loop(self):
        """Retry loop to establish connection."""
        use_tls = config['mqtt']['tls']
        fallback_happened = False

        while not self._stopper.is_set():
            if not self._mqttc and not self._setup_mqtt_client(use_tls):
                 time.sleep(config['mqtt']['connect_retry'])
                 continue

            plain_port = int(config['mqtt']['port'])
            tls_port = int(config['mqtt']['tls_port'])
            current_port = tls_port if use_tls else plain_port

            logger.debug(f"Connecting to MQTT Broker '{config['mqtt']['host']}:{current_port}' (TLS: {use_tls})")
            
            try:
                self._mqttc.connect(config['mqtt']['host'], current_port, 60)
                self._mqttc.loop_start()
                
                # Wait for connection to be established via on_connect callback
                timeout = time.time() + 10 
                while time.time() < timeout and not self._connected and not self._stopper.is_set():
                    time.sleep(0.5)

                if self._connected:
                    logger.debug("MQTT connection established")
                    return # Connected
                else:
                    raise ConnectionError("Timeout waiting for MQTT CONNACK")

            except (ssl.SSLError, ssl.CertificateError, ConnectionResetError, ConnectionError, OSError) as e:
                if self._mqttc:
                    self._mqttc.loop_stop()
                    self._mqttc = None # force reset

                if use_tls and not fallback_happened:
                    SetError(f"MQTT TLS connection failed: {type(e).__name__}: '{str(e)}'. Falling back to plain MQTT.", category='mqtt')
                    use_tls = False
                    fallback_happened = True
                else:
                    SetError(f"MQTT connection failed: {type(e).__name__}: '{str(e)}'", category='mqtt')
                    time.sleep(config['mqtt']['connect_retry'])
            except Exception as e:
                if self._mqttc:
                    self._mqttc.loop_stop()
                    self._mqttc = None
                SetError(f"MQTT connection failed unexpectedly: {type(e).__name__}: '{str(e)}'", category='mqtt')
                time.sleep(config['mqtt']['connect_retry'])

    def _publish_diagnostics(self):
        """Publish dynamic diagnostics info."""
        try:
            current_diagnostics = {
                'version': s0pcmreaderversion,
                'firmware': s0pcm_firmware,
                'startup_time': startup_time,
                'port': config['serial']['port']
            }

            for key, val in current_diagnostics.items():
                if key not in self._last_diagnostics or self._last_diagnostics[key] != val:
                    topic = config['mqtt']['base_topic'] + '/' + key
                    self._mqttc.publish(topic, str(val), retain=config['mqtt']['retain'])
                    self._last_diagnostics[key] = val
            
            # Legacy JSON info
            info_payload = {
                "version": s0pcmreaderversion,
                "s0pcm_firmware": s0pcm_firmware,
                "startup_time": startup_time,
                "serial_port": config['serial']['port']
            }
            self._mqttc.publish(config['mqtt']['base_topic'] + '/info', json.dumps(info_payload), retain=config['mqtt']['retain'])
        except Exception as e:
            logger.error(f"Failed to publish info state to MQTT: {e}")

    def _publish_measurements(self, measurementlocal, measurementprevious):
        """Publish meter values."""
        for key in measurementlocal:
            if isinstance(key, int):
                # Filter logic
                if config['s0pcm']['include'] is not None and key not in config['s0pcm']['include']:
                        logger.debug(f"MQTT Publish for input '{key}' is disabled")
                        continue
                if not measurement[key].get('enabled', True):
                        continue

                jsondata = {}
                instancename = measurementlocal[key].get('name', str(key))

                for subkey in ['total', 'today', 'yesterday']:
                    value_previous = measurementprevious.get(key, {}).get(subkey, -1)
                    
                    try:
                        if subkey in measurementlocal[key]:
                            if config['mqtt']['split_topic'] == True:
                                # On-change check
                                if measurementlocal[key][subkey] == value_previous and config['s0pcm']['publish_onchange'] == True:
                                    continue
                                
                                
                                logger.debug(f"MQTT Publish: topic='{config['mqtt']['base_topic']}/{instancename}/{subkey}', value='{measurementlocal[key][subkey]}'")
                                self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey, measurementlocal[key][subkey], retain=config['mqtt']['retain'])
                            else:
                                jsondata[subkey] = measurementlocal[key][subkey]

                    except Exception as e:
                        SetError(f"MQTT Publish Failed for {instancename}/{subkey}. {type(e).__name__}: '{str(e)}'", category='mqtt')

                # Publish JSON if not split
                if config['mqtt']['split_topic'] == False and jsondata:
                    try:
                        logger.debug(f"MQTT Publish JSON: topic='{config['mqtt']['base_topic']}/{instancename}', value='{json.dumps(jsondata)}'")
                        self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata), retain=config['mqtt']['retain'])
                    except Exception as e:
                        SetError(f"MQTT Publish Failed for {instancename} (JSON). {type(e).__name__}: '{str(e)}'", category='mqtt')

    def _main_loop(self):
        """Main processing loop when connected."""
        measurementprevious = {}
        # Initial sync - removed pre-population to force first publish of all values
        # This ensures that any name/topic changes are immediately visible on startup.

        while not self._stopper.is_set():
            # Snapshot data
            with lock:
                measurementlocal = copy.deepcopy(measurementshare)
                errorlocal = lasterrorshare

            # Connection check - if lost, return to connect loop to trigger re-connection logic
            if not self._connected:
                logger.warning('MQTT Connection lost, returning to connect loop...')
                return 

            if not self._discovery_sent:
                self.send_discovery(measurementlocal)

            self._publish_diagnostics()
            self._publish_measurements(measurementlocal, measurementprevious)

            # Publish Error
            error_published = False
            try:
                error_payload = errorlocal if errorlocal else "No Error"
                self._mqttc.publish(config['mqtt']['base_topic'] + '/error', error_payload, retain=config['mqtt']['retain'])
                error_published = True
            except Exception as e:
                SetError(f"MQTT Publish Failed for error topic. {type(e).__name__}: '{str(e)}'", category='mqtt')

            if self._connected and error_published:
                SetError(None, category='mqtt', trigger_event=False)

            measurementprevious = copy.deepcopy(measurementlocal)

            # Wait period
            if config['s0pcm']['publish_interval'] is None:
                self._trigger.wait()
            else:
                self._trigger.wait(timeout=config['s0pcm']['publish_interval'])
            self._trigger.clear()

    def run(self):
        try:
            while not self._stopper.is_set():
                # Establish connection
                self._connect_loop()
                # Run main logic
                self._main_loop()
                # If _main_loop returns, it means we stopped or need full reconnect
                if self._mqttc:
                    if self._connected:
                         self._mqttc.publish(config['mqtt']['base_topic'] + '/status', config['mqtt']['offline'], retain=config['mqtt']['retain'])
                    self._mqttc.loop_stop()
                    self._mqttc.disconnect()
                    self._mqttc = None
        except Exception:
            logger.error('Fatal exception has occured', exc_info=True)
        finally:
            self._stopper.set()

# ------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------

def main():
    global measurementshare, trigger, stopper

    # Signal handling for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Signal {signum} received, stopping...")
        stopper.set()
        trigger.set() # Wake up threads waiting on trigger

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        ReadConfig()
        ReadMeasurement()
        # Initialize measurementshare
        measurementshare = copy.deepcopy(measurement)
    except Exception:
        logger.error('Fatal exception during startup', exc_info=True)
        sys.exit(1)

    trigger = threading.Event()
    stopper = threading.Event()

    logger.info('Starting s0pcm-reader...')

    # Start our SerialPort thread
    t1 = TaskReadSerial(trigger, stopper)
    t1.start()

    # Start our MQTT thread
    t2 = TaskDoMQTT(trigger, stopper)
    t2.start()

    # Wait for threads to finish (which happens when stopper is set)
    # We use a loop with timeout to allow signal handling to interrupt main thread in Python
    while t1.is_alive() or t2.is_alive():
        t1.join(1)
        t2.join(1)

    logger.info('Stop: s0pcm-reader')

if __name__ == "__main__":
    main()
