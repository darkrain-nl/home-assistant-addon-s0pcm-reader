
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
s0pcmreaderversion = '2024.02.17'

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
    if not 'port' in config['mqtt']: config['mqtt']['port'] = 1883
    if not 'username' in config['mqtt']: config['mqtt']['username'] = None
    if not 'password' in config['mqtt']: config['mqtt']['password'] = None
    if not 'base_topic' in config['mqtt']: config['mqtt']['base_topic'] = 's0pcm-reader'
    if not 'client_id' in config['mqtt']: config['mqtt']['client_id'] = None
    if not 'version' in config['mqtt']: config['mqtt']['version'] = mqtt.MQTTv5
    if not 'retain' in config['mqtt']: config['mqtt']['retain'] = True
    if not 'split_topic' in config['mqtt']: config['mqtt']['split_topic'] = True
    if not 'connect_retry' in config['mqtt']: config['mqtt']['connect_retry'] = 5
    if not 'online' in config['mqtt']: config['mqtt']['online'] = 'online'
    if not 'offline' in config['mqtt']: config['mqtt']['offline'] = 'offline'
    if not 'lastwill' in config['mqtt']: config['mqtt']['lastwill'] = 'offline'

    if str(config['mqtt']['version']) == '3.1':
      config['mqtt']['version'] = mqtt.MQTTv31
    elif str(config['mqtt']['version']) == '3.1.1':
      config['mqtt']['version'] = mqtt.MQTTv311
    else:
      config['mqtt']['version'] = mqtt.MQTTv5
 
    # TLS configuration
    if not 'tls' in config['mqtt']: config['mqtt']['tls'] = False
    if not 'tls_ca' in config['mqtt']: config['mqtt']['tls_ca'] = ''
    if not 'tls_check_peer' in config['mqtt']: config['mqtt']['tls_check_peer'] = True

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
    
    logger.debug('Config: %s', str(config))

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

    # check date format
    if 'date' in measurement:
        # check date format
        try:
            measurement['date'] = datetime.datetime.strptime(str(measurement['date']), '%Y-%m-%d')
            measurement['date'] = measurement['date'].date()
        except ValueError:
            logger.error('\'%s\' has an invalid date field \'%s\', default to today \'%s\'', measurementname, str(measurement['date']), str(datetime.date.today()))
            measurement['date'] = datetime.date.today()
    else:
        measurement['date'] = datetime.date.today()

    logger.debug('Measurement: %s', str(measurement))

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
                logger.error('Serialport connection failed. %s: \'%s\'', type(e).__name__, str(e))
                logger.error('Retry in %d seconds', config['serial']['connect_retry'])
                time.sleep(config['serial']['connect_retry'])
                continue

            # Only do a read of the data when the port is opened succesfully
            while not self._stopper.is_set():

                try:
                    datain = ser.readline()
                except Exception as e:
                    logger.error('Serialport read error. %s: \'%s\'', type(e).__name__, str(e))
                    ser.close()
                    break
             
                # check if there is data received
                # If there is really nothing, most likely a timeout on reading the input data
                if len(datain) == 0:
                    logger.error('Failed to read any data (timeout)')
                    ser.close()
                    break

                # need to decode the data to ascii string
                try:
                    datastr = datain.decode('ascii')
                except UnicodeDecodeError:
                    logger.error('Failed to decode \'%s\'', str(datain))
                    continue

                # Need to remove '\r\n' from the input
                datastr = datastr.rstrip('\r\n')

                if datastr.startswith('/'):
                    logger.debug('Header Packet: \'%s\'', datastr)
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
                        logger.error('Packet has invalid length. Excepted 10 or 19, got %d.', len(s0arr))
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
                                logger.error('Cannot convert pulsecount \'%s\' into integer, received \'%s\'', s0arr[offset], s0arr[offset + 2])
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
                                        logger.error('Stats file \'%s\' write/create failed. %s: \'%s\'', configdirectory + 'daily-' + str(count) + '.txt', type(e).__name__, str(e))
                            
                            if pulsecount > measurement[count]['pulsecount']:

                                logger.debug('Pulsecount changed from \'%d\' to \'%d\'', measurement[count]['pulsecount'], pulsecount)

                                # Pulsecount has changed, lets do some magic :-)
                                delta = pulsecount - measurement[count]['pulsecount']
                                measurement[count]['pulsecount'] = pulsecount
                                measurement[count]['total'] += delta
                                measurement[count]['today'] += delta

                            elif pulsecount < measurement[count]['pulsecount']:
                                logger.warning('Stored pulsecount \'%s\' is higher then read, this normally happens if the s0pcm is restarted. We will continue counting, but for an precise value, read the meter value and correct the totals in the \'%s\' file', s0arr[offset], measurementname)
                                delta = pulsecount
                                measurement[count]['pulsecount'] = pulsecount
                                measurement[count]['total'] += delta
                                measurement[count]['today'] += delta

                        else:
                            logger.error('Expecting \'M%s\', received \'%s\'', str(count), s0arr[offset])
                            continue

                    # Update todays date - but we don't convert to str yet, it looks nicer without it in the yaml file ;-)
                    if str(measurement['date']) != str(datetime.date.today()):
                        measurement['date'] = datetime.date.today()

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
                    logger.error('Invalid Packet: \'%s\'', datastr)

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

    def on_connect(self, mqttc, obj, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            logger.debug('MQTT successfully connected to broker')
            self._mqttc.publish(config['mqtt']['base_topic'] + '/status', config['mqtt']['online'], retain=config['mqtt']['retain'])
        else:
            self._connected = False

    def on_disconnect(self, mqttc, userdata, reason_code, properties):
        self._connected = False
        if reason_code == 0:
            logger.debug('MQTT successfully disconnected to broker')
        else:
            logger.error('MQTT failed to connect to broker \'%s\', retrying.', mqtt.connack_string(reason_code))

    def on_message(self, mqttc, obj, msg):
        logger.debug('MQTT on_message: ' + msg.topic + ' ' + str(msg.qos) + ' ' + str(msg.payload))

    def on_publish(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_publish: mid: ' + str(mid))

    def on_subscribe(self, mqttc, obj, mid, granted_qos):
        logger.debug('MQTT on_subscribe: ' + str(mid) + ' ' + str(granted_qos))

    def on_log(self, mqttc, obj, level, string):
        logger.debug('MQTT on_log: ' + string)

    def DoMQTT(self):

        global measurementshare
        measurementprevious = {}

        # Copy the measurements to previous one, preventing send values when on change is enabled
        measurementprevious = measurement

        # Define our MQTT Client
        self._mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config['mqtt']['client_id'], protocol=config['mqtt']['version'])
        self._mqttc.on_connect = self.on_connect
        self._mqttc.on_disconnect = self.on_disconnect
        #self._mqttc.on_message = self.on_message
        #self._mqttc.on_publish = self.on_publish
        #self._mqttc.on_subscribe = self.on_subscribe

        # https://github.com/eclipse/paho.mqtt.python/blob/master/examples/client_pub-wait.py

        if config['mqtt']['username'] != None:
            self._mqttc.username_pw_set(config['mqtt']['username'], config['mqtt']['password'])

        # Setup TLS if requested
        if config['mqtt']['tls']:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS)

            if config['mqtt']['tls_ca'] == '':
                context.verify_mode = ssl.CERT_NONE
                context.check_hostname = False
            else:
                context.verify_mode = ssl.CERT_REQUIRED
                context.load_verify_locations(cafile=config['mqtt']['tls_ca'])
                context.check_hostname = config['mqtt']['tls_check_peer']

            self._mqttc.tls_set_context(context=context)

        # Set last will
        self._mqttc.will_set(config['mqtt']['base_topic'] + '/status', config['mqtt']['lastwill'], retain=config['mqtt']['retain'])

        while not self._stopper.is_set():

            logger.debug('Connecting to MQTT Broker \'%s:%s\'', config['mqtt']['host'], str(config['mqtt']['port']))

            try:
                self._mqttc.connect(config['mqtt']['host'], int(config['mqtt']['port']), 60)
            except Exception as e:
                logger.error('MQTT connection failed. %s: \'%s\'', type(e).__name__, str(e))
                logger.error('Retry in %d seconds', config['mqtt']['connect_retry'])
                time.sleep(config['mqtt']['connect_retry'])
                continue

            #connect_async(host, port=1883, keepalive=60, bind_address="")
            self._mqttc.loop_start()

            # Let's wait 1 second, otherwise we can be too fast?
            time.sleep(1)

            while not self._stopper.is_set():
                #Do our publish here with information we get from other Thread

                # If no interval is defined, we wait on an event from the other thread
                # We need to clear it (directly), otherwise it will run at  100% cpu
                if config['s0pcm']['publish_interval'] == None:
                    self._trigger.wait()
                    self._trigger.clear()

                # Do some lock/release on global variables
                lock.acquire()
                measurementlocal = copy.deepcopy(measurementshare)
                lock.release()

                # Check if we are connected
                if self._connected == False:
                    logger.debug('Not connected to MQTT Broker')
                    if config['s0pcm']['publish_interval'] != None:
                        time.sleep(config['s0pcm']['publish_interval'])
                    continue

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
                                logger.error('MQTT Publish Failed. Key=%s, SubKey=%s. %s: \'%s\'', str(key), subkey, type(e).__name__, str(e))

                        # We should publish the json value
                        if config['mqtt']['split_topic'] == False:
                            try:
                                logger.debug('MQTT Publish of topic \'%s\' and value \'%s\'',config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata))

                                # Do a MQTT Publish
                                self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata), retain=config['mqtt']['retain'])
                            except Exception as e:
                                logger.error('MQTT Publish Failed. %s: \'%s\'', type(e).__name__, str(e))

                # Lets make also a copy of this one, then we can compare if there is a delta
                measurementprevious = copy.deepcopy(measurementlocal)

                # Now sleep according to publish interval
                if config['s0pcm']['publish_interval'] != None:
                    time.sleep(config['s0pcm']['publish_interval'])

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
