
import datetime
import time
import threading
import serial
import yaml
import logging
import paho.mqtt.client as mqtt
import ssl
import argparse
import copy
import json
import os
import sys
import re
import signal
import shutil
import urllib.request

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

lock = threading.RLock()

# ------------------------------------------------------------------------------------
# Global Variables
# ------------------------------------------------------------------------------------
config = {}
measurement = {'date': datetime.date.today()}
measurementshare = {}
lasterror_serial = None
lasterror_mqtt = None
lasterrorshare = None

# Metadata
startup_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
s0pcm_firmware = "Unknown"

# Stateless Synchronization
recovery_event = threading.Event()

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
# Determine default config directory: /data for HA, ./ for local dev
default_config = '/data' if os.path.exists('/data') else './'
parser.add_argument('-c', '--config', help='Directory where the configuration resides', type=str, default=default_config)
args = parser.parse_args()

configdirectory = args.config
if not configdirectory.endswith('/'):
    configdirectory += '/'

# ------------------------------------------------------------------------------------
# Setup filenames
# ------------------------------------------------------------------------------------
configname = configdirectory + 'configuration.json'
measurementname = configdirectory + 'measurement.json'

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


def GetSupervisorConfig(service):
    """Fetch service configuration (like MQTT) from the Home Assistant Supervisor API."""
    token = os.getenv('SUPERVISOR_TOKEN')
    if not token:
        return {}

    url = f"http://supervisor/services/{service}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get('data', {})
    except Exception as e:
        logger.debug(f"Supervisor API discovery for {service} failed: {e}")
    return {}

def MigrateData():
    """Migrate data from legacy /share/s0pcm location and from YAML to JSON."""
    legacy_dir = '/share/s0pcm/'
    
    if os.path.exists(legacy_dir) and configdirectory == '/data/':
        logger.info(f"Checking for legacy data in {legacy_dir}...")
        try:
            # 1. Migrate daily stats files
            files_to_migrate = [f for f in os.listdir(legacy_dir) if f.startswith('daily-') and f.endswith('.txt')]
            files_to_migrate.extend(['measurement.json', 'measurement.yaml'])

            for f in files_to_migrate:
                src = os.path.join(legacy_dir, f)
                dst = os.path.join(configdirectory, f)
                
                # Skip if already migrated
                if os.path.exists(dst + ".migrated") or os.path.exists(dst.replace('.json', '.yaml') + ".migrated"):
                    continue

                # Copy if source exists and destination doesn't
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    logger.info(f"Successfully migrated {f} to {configdirectory}")
        except Exception as e:
            logger.error(f"Failed to migrate legacy files from {legacy_dir}: {e}")

    # 2. Migrate from measurement.yaml to measurement.json if needed
    yaml_path = os.path.join(configdirectory, 'measurement.yaml')
    json_path = os.path.join(configdirectory, 'measurement.json')
    
    if os.path.exists(yaml_path):
        perform_conversion = False
        if not os.path.exists(json_path) and not os.path.exists(json_path + ".migrated") and not os.path.exists(yaml_path + ".migrated"):
            perform_conversion = True
        else:
            # Check if existing json is "empty" (no meter data)
            try:
                with open(json_path, 'r') as fj:
                    existing_data = json.load(fj)
                    # If it's just a date or empty, we consider it a candidate for overwrite
                    if not existing_data or (len(existing_data) == 1 and 'date' in existing_data):
                        logger.info(f"Existing {json_path} appears empty/default, allowing migration to overwrite.")
                        perform_conversion = True
            except Exception:
                perform_conversion = True # If we can't read it, allow overwrite

        if perform_conversion:
            try:
                with open(yaml_path, 'r') as f:
                    data = yaml.safe_load(f)
                    if data:
                        with open(json_path, 'w') as fj:
                            # Convert date object to string for JSON
                            if 'date' in data and isinstance(data['date'], (datetime.date, datetime.datetime)):
                                data['date'] = str(data['date'])
                            json.dump(data, fj, indent=4)
                        logger.info(f"Successfully migrated data from {yaml_path} to {json_path}")
                        # Rename yaml to prevent re-migration loop
                        os.rename(yaml_path, yaml_path + ".migrated")
            except Exception as e:
                logger.error(f"Failed to migrate YAML measurement data to JSON: {e}")

def PushLegacyToMQTT(mqttc):
    """One-time push of legacy measurement.json data to MQTT retained topics."""
    global measurement
    if not os.path.exists(measurementname):
        return

    logger.info(f"Migration: Pushing legacy data from {measurementname} to MQTT...")
    try:
        with open(measurementname, 'r') as f:
            data = json.load(f)
            if not data:
                return

            base_topic = config['mqtt']['base_topic']
            retain = config['mqtt']['retain']

            # Push global date
            if 'date' in data:
                mqttc.publish(f"{base_topic}/date", str(data['date']), retain=retain)

            # Push meter data
            for key, mdata in data.items():
                if not isinstance(mdata, dict):
                    continue
                
                # ID-based topics for internal state
                for field in ['total', 'today', 'yesterday', 'pulsecount']:
                    if field in mdata:
                        mqttc.publish(f"{base_topic}/{key}/{field}", mdata[field], retain=retain)
                
                # Name
                if 'name' in mdata:
                    mqttc.publish(f"{base_topic}/{key}/name", mdata['name'], retain=retain)

            logger.info("Migration: Legacy data successfully pushed to MQTT. You can now safely remove measurement.json.")
            
            # Rename legacy file to prevent re-migration
            backup_name = measurementname + ".migrated"
            os.rename(measurementname, backup_name)
            logger.info(f"Migration: Renamed {measurementname} to {backup_name}")

    except Exception as e:
        logger.error(f"Migration: Failed to push legacy data to MQTT: {e}")

# ------------------------------------------------------------------------------------
# Read the configuration
# ------------------------------------------------------------------------------------
def ReadConfig():

    global config

    # 1. Attempt to load HA Options if they exist
    options_path = '/data/options.json'
    ha_options = {}
    if os.path.exists(options_path):
        try:
            with open(options_path, 'r') as f:
                ha_options = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {options_path}: {e}")

    # 2. Attempt to load legacy configuration.json if it exists
    try:
        with open(configname, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        if not ha_options:
            print(f"WARN: No configuration file found, using defaults.")
    except Exception as e:
        logger.error(f"Error reading {configname}: {e}")

    # 3. Merge/Map HA Options into the config structure
    if ha_options:
        config.setdefault('log', {})
        if 'log_level' in ha_options: config['log']['level'] = ha_options['log_level']
        if 'log_size' in ha_options: config['log']['size'] = ha_options['log_size']
        if 'log_count' in ha_options: config['log']['count'] = ha_options['log_count']
        
        config.setdefault('serial', {})
        if 'device' in ha_options: config['serial']['port'] = ha_options['device']

        config.setdefault('mqtt', {})
        
        # Service Discovery if host not manually set
        if not ha_options.get('mqtt_host'):
            mqtt_service = GetSupervisorConfig('mqtt')
            if mqtt_service:
                logger.info("Using MQTT service discovery for connection settings.")
                config['mqtt']['host'] = mqtt_service.get('host', 'core-mosquitto')
                config['mqtt']['username'] = mqtt_service.get('username')
                config['mqtt']['password'] = mqtt_service.get('password')
                config['mqtt']['port'] = mqtt_service.get('port', 1883)
        
        # Manual Overrides from HA options
        mapping = {
            'mqtt_host': 'host',
            'mqtt_port': 'port',
            'mqtt_username': 'username',
            'mqtt_password': 'password',
            'mqtt_client_id': 'client_id',
            'mqtt_base_topic': 'base_topic',
            'mqtt_protocol': 'version',
            'mqtt_discovery': 'discovery',
            'mqtt_discovery_prefix': 'discovery_prefix',
            'mqtt_retain': 'retain',
            'mqtt_split_topic': 'split_topic',
            'mqtt_tls': 'tls',
            'mqtt_tls_port': 'tls_port',
            'mqtt_tls_ca': 'tls_ca',
            'mqtt_tls_check_peer': 'tls_check_peer'
        }
        for ha_key, cfg_key in mapping.items():
            if ha_options.get(ha_key) is not None:
                config['mqtt'][cfg_key] = ha_options[ha_key]

    # Setup 'log' variables
    config.setdefault('log', {})
    if config['log'] is None: config['log'] = {}

    config['log'].setdefault('level', 'INFO')
    if config['log']['level'] in [None, ""]: config['log']['level'] = 'INFO'
    config['log']['level'] = config['log']['level'].upper()

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
# Save the measurement data
# ------------------------------------------------------------------------------------
def SaveMeasurement():
    """No-op in stateless mode. Persistence is handled via MQTT retained messages."""
    pass

# ------------------------------------------------------------------------------------
# Read the measurement data
# ------------------------------------------------------------------------------------
def ReadMeasurement():

    global measurement

    try:
        with open(measurementname, 'r') as f:
            data = json.load(f)
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

    # JSON keys are always strings, convert meter IDs back to integers
    new_measurement = {}
    for k, v in measurement.items():
        try:
            new_measurement[int(k)] = v
        except ValueError:
            new_measurement[k] = v
    measurement = new_measurement

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
        with lock:
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

            # Update shared state
            measurementshare = copy.deepcopy(measurement)
        
        # Valid packet processed
        SetError(None, category='serial')
        
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
            # Wait for MQTT recovery to complete before starting to process serial data
            logger.info("Serial Task: Waiting for MQTT/HA state recovery...")
            recovery_event.wait()
            logger.info("Serial Task: Recovery complete, starting serial read loop.")

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
        self._global_discovery_sent = False
        self._discovered_meters = {} # Track {meter_id: "name"}
        self._recovery_complete = False
        self._mqttc = None
        self._last_diagnostics = {}

    def _fetch_ha_state(self, entity_id):
        """Fetch the current state of an entity from Home Assistant REST API."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token:
            return None

        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    state = data.get('state')
                    if state not in [None, 'unknown', 'unavailable']:
                        return state
        except Exception as e:
            logger.debug(f"HA API state fetch for {entity_id} failed: {e}")
        return None

    def _fetch_all_ha_states(self):
        """Fetch all entity states from Home Assistant."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token:
            return []

        url = "http://supervisor/core/api/states"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    return json.loads(response.read().decode())
        except Exception as e:
            logger.error(f"HA API failed to fetch all states: {e}")
        return []

    def _recover_state(self):
        """Startup phase: Wait for retained messages or HA API to recover meter totals."""
        global measurement, measurementshare
        
        # We always perform recovery now as we are stateless
        logger.info("Starting State Recovery phase...")
        
        # 1. Push legacy data if it exists
        PushLegacyToMQTT(self._mqttc)

        logger.info("Waiting 7s for retained MQTT messages...")
        recovered_data = {} # {identifier: {'total': X, 'today': Y, 'yesterday': Z, 'pulsecount': P}}
        recovered_names = {} # {name: id}
        recovered_date = None
        
        base_topic = config['mqtt']['base_topic']
        discovery_prefix = config['mqtt']['discovery_prefix']

        def on_recovery_message(client, userdata, msg):
            nonlocal recovered_date
            try:
                # 0. Global Date
                if msg.topic == f"{base_topic}/date":
                    recovered_date = msg.payload.decode().strip()
                    logger.debug(f"Recovery: Found global date: {recovered_date}")
                    return

                # 1. Handle Discovery topics to rebuild name-to-id mapping
                if '/config' in msg.topic:
                    logger.debug(f"Recovery: Processing discovery packet: {msg.topic}")
                    payload = json.loads(msg.payload.decode())
                    unique_id = payload.get('unique_id', '')
                    state_topic = payload.get('state_topic', '')
                    
                    # Extract ID from unique_id: s0pcm_base_ID_subkey (e.g. s0pcm_s0pcmreader_1_total)
                    match_id = re.search(fr"s0pcm_{base_topic}_(\d+)", unique_id)
                    if match_id:
                        meter_id = int(match_id.group(1))
                        # Extract Name from state_topic: base/NAME/subkey
                        name_part = state_topic.replace(f"{base_topic}/", "")
                        name = name_part.split('/')[0]
                        if name and name != str(meter_id):
                            recovered_names[name] = meter_id
                            logger.debug(f"Recovery: Mapped Name '{name}' to ID {meter_id}")
                    return

                # 2. Handle Data topics (total, today, yesterday, pulsecount)
                # Expected topics: base_topic/ID_or_NAME/SUFFIX
                topic_parts = msg.topic.split('/')
                if len(topic_parts) >= 3:
                    suffix = topic_parts[-1]
                    if suffix in ['total', 'today', 'yesterday', 'pulsecount']:
                        identifier = topic_parts[-2]
                        payload = msg.payload.decode()
                        try:
                            # We treat it as float first to be safe, then int
                            value = int(float(payload))
                            recovered_data.setdefault(identifier, {})[suffix] = value
                            logger.debug(f"Recovery: Found {identifier} {suffix} = {value}")
                        except ValueError:
                            pass
            except Exception as e:
                logger.debug(f"Recovery parse error: {e}")

        # Set temporary callback
        original_on_message = self._mqttc.on_message
        self._mqttc.on_message = on_recovery_message
        
        # Subscribe to totals, stats, and discovery topics
        topics = [
            f"{base_topic}/date",
            f"{base_topic}/+/total", 
            f"{base_topic}/+/today", 
            f"{base_topic}/+/yesterday",
            f"{base_topic}/+/pulsecount",
            f"{discovery_prefix}/sensor/{base_topic}/#"
        ]
        for t in topics:
            self._mqttc.subscribe(t)
        
        # Wait for messages
        time.sleep(7)
        
        for t in topics:
            self._mqttc.unsubscribe(t)
        self._mqttc.on_message = original_on_message
        
        if recovered_data:
            logger.info(f"Recovery: Received {len(recovered_data)} unique identifier states from MQTT.")
            with lock:
                # Map recovered data to meters
                for identifier, data in recovered_data.items():
                    meter_id = None
                    # 1. Try numeric ID
                    try:
                        meter_id = int(identifier)
                    except ValueError:
                        # 2. Try mapped names from discovery
                        meter_id = recovered_names.get(identifier)
                        
                        # 3. Try current known names (unlikely on fresh start, but good safety)
                        if not meter_id:
                            for mid, mdata in measurement.items():
                                if isinstance(mid, int) and mdata.get('name') == identifier:
                                    meter_id = mid
                                    break
                    
                    if meter_id:
                        measurement.setdefault(meter_id, {})
                        
                        # Restore the name if we found a mapping for this ID
                        for name, mid in recovered_names.items():
                            if mid == meter_id:
                                measurement[meter_id]['name'] = name
                                break

                        for field in ['total', 'today', 'yesterday', 'pulsecount']:
                            if field in data:
                                # We set the field even if it's 0
                                # But we only log if it's > 0 or previously missing
                                if field not in measurement[meter_id] or data[field] > measurement[meter_id].get(field, 0):
                                    measurement[meter_id][field] = data[field]
                                    logger.info(f"Recovered {field} for meter {meter_id} from MQTT: {data[field]}")
                
                # Restore date
                if recovered_date:
                    measurement['date'] = recovered_date

        # 3. Fallback to HA API for missing meters
        # We check meters 1 to 5 (standard S0PCM-5)
        all_states = None
        for meter_id in range(1, 6):
            if meter_id not in measurement or 'total' not in measurement[meter_id]:
                logger.info(f"Recovery: Meter {meter_id} not found on MQTT, attempting HA API fallback...")
                
                # Phase A: Try specific patterns (fast)
                entity_patterns = [
                    f"sensor.{base_topic}_{meter_id}_total",
                    f"sensor.s0pcm_reader_{meter_id}_total",
                    f"sensor.{meter_id}_total"
                ]
                
                ha_total = None
                for ha_entity in entity_patterns:
                    ha_total = self._fetch_ha_state(ha_entity)
                    if ha_total:
                        break
                
                # Phase B: Fuzzy search across ALL entities if Phase A failed
                # For safety, we only perform fuzzy recovery for Meters 1 and 2 by default
                if not ha_total and meter_id <= 2:
                    if all_states is None:
                        logger.debug("Recovery: Fetching all HA states for fuzzy matching...")
                        all_states = self._fetch_all_ha_states()
                    
                    # Search patterns for this meter_id
                    keywords = ['total', 'totaal', 'today', 'vandaag', 'dag']
                    exclude_keywords = ['cost', 'prijs', 'price', 'integral', 'energy', 'gas', 'power', 'spanning', 'stroom', 'consumption', 'delivery', 'koffie', 'coffee']
                    
                    for item in all_states:
                        entity_id = item.get('entity_id', '').lower()
                        state_str = str(item.get('state', '')).lower()
                        
                        # Check if this entity is a plausible candidate for this meter_id
                        is_match = False
                        
                        # Domain Lock: Only consider if it belongs to S0PCM Reader specifically
                        is_our_domain = (base_topic in entity_id) or entity_id.startswith("sensor.s0pcm_")
                        
                        # 1. ID based match: sensor.s0pcm_1_total, sensor.meter_1, etc.
                        if is_our_domain:
                            if f"_{meter_id}_" in entity_id or entity_id.endswith(f"_{meter_id}"):
                                if any(k in entity_id for k in keywords):
                                    is_match = True
                        
                        # 2. Specific fallback for Meter 1 (Water) if it was renamed to something generic like "Watermeter Totaal"
                        if not is_match and meter_id == 1:
                            if "watermeter_totaal" in entity_id or "watermeter_total" in entity_id:
                                is_match = True

                        if is_match:
                            # Strict Exclusions: Never pick up costs, integrals, or energy prices
                            if any(x in entity_id for x in exclude_keywords):
                                logger.debug(f"Recovery: Skipping {entity_id} for Meter {meter_id} (Matched exclusion keyword)")
                                continue

                            if state_str in [None, 'unknown', 'unavailable', '']:
                                logger.debug(f"Recovery: Skipping {entity_id} for Meter {meter_id} (State is '{state_str}')")
                                continue

                            # Clean the state string (remove units, handle European thousand separators)
                            # e.g. "1.323.394 m3" -> "1323394"
                            clean_state = state_str
                            for unit in ['m³', 'm3', 'kwh', 'l/min', 'l']:
                                if unit in clean_state:
                                    clean_state = clean_state.replace(unit, '')
                            
                            # Remove non-numeric chars except . , and -
                            clean_state = "".join(c for c in clean_state if c.isdigit() or c in '.,-')
                            
                            # If it has multiple dots/commas, it's likely thousand separators
                            if clean_state.count('.') > 1 or clean_state.count(',') > 1 or (clean_state.count('.') == 1 and clean_state.count(',') == 1):
                                clean_state = clean_state.replace('.', '').replace(',', '')
                            elif clean_state.count(',') == 1 and '.' not in clean_state:
                                # Likely decimal comma (European), treat as dot for float()
                                clean_state = clean_state.replace(',', '.')
                            
                            clean_state = clean_state.strip()
                            
                            try:
                                if not clean_state: continue
                                val = float(clean_state)
                                ha_total = str(val)
                                logger.info(f"Recovery: Found surgical match for Meter {meter_id}: {entity_id} = {ha_total} (was '{state_str}')")
                                break
                            except ValueError:
                                logger.debug(f"Recovery: Skipping {entity_id} - could not parse '{clean_state}' as number")
                                continue

                if ha_total:
                    try:
                        total_val = int(float(ha_total))
                        with lock:
                            measurement.setdefault(meter_id, {})['total'] = total_val
                            measurement[meter_id].setdefault('today', 0)
                            measurement[meter_id].setdefault('yesterday', 0)
                            measurement[meter_id].setdefault('pulsecount', 0)
                        logger.info(f"Recovery: Recovered total for meter {meter_id} from HA API: {total_val}")
                    except ValueError:
                        pass
        
        # Finalize
        with lock:
            measurementshare = copy.deepcopy(measurement)
        
        self._recovery_complete = True
        recovery_event.set() # Signal Serial Task to start
        logger.info("State Recovery complete.")

    def on_connect(self, mqttc, obj, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            self._discovery_sent = False
            logger.debug('MQTT successfully connected to broker')
            self._trigger.set()
            self._mqttc.publish(config['mqtt']['base_topic'] + '/status', config['mqtt']['online'], retain=config['mqtt']['retain'])
            
            # Subscribe to 'set' commands
            self._mqttc.subscribe(config['mqtt']['base_topic'] + '/+/total/set')
            self._mqttc.subscribe(config['mqtt']['base_topic'] + '/+/name/set')
            logger.debug(f"Subscribed to set commands under {config['mqtt']['base_topic']}/+/...")
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

        # Check for set commands
        if msg.topic.endswith('/total/set'):
            self._handle_set_command(msg)
        elif msg.topic.endswith('/name/set'):
            self._handle_name_set(msg)

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
                SaveMeasurement()
                logger.debug(f"Updated measurement file with new total for meter {meter_id}")

                # Update share and trigger publish
                measurementshare = copy.deepcopy(measurement)
                self._trigger.set()

        except Exception as e:
            SetError(f"Failed to process MQTT set command: {e}", category='mqtt')

    def _handle_name_set(self, msg):
        """Handle MQTT command to set or clear a meter name."""
        global measurementshare
        try:
            # Topic format: base_topic/ID_or_NAME/name/set
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
                SetError(f"Ignored name/set command for unknown meter ID or Name: {identifier}", category='mqtt')
                return

            new_name = msg.payload.decode('utf-8').strip()
            
            # If payload is empty, clear the name
            if not new_name:
                new_name = None

            logger.info(f"Received MQTT name/set command for meter {meter_id}. Setting name to: {new_name or 'None (ID only)'}")

            with lock:
                if meter_id not in measurement:
                    measurement[meter_id] = {}
                    measurement[meter_id].setdefault('pulsecount', 0)
                    measurement[meter_id].setdefault('total', 0)
                    measurement[meter_id].setdefault('today', 0)
                    measurement[meter_id].setdefault('yesterday', 0)

                if new_name:
                    measurement[meter_id]['name'] = new_name
                else:
                    if 'name' in measurement[meter_id]:
                        del measurement[meter_id]['name']
                
                # Persist immediately
                SaveMeasurement()
                
                # Update share and trigger discovery to update HA entities
                measurementshare = copy.deepcopy(measurement)
                self.send_discovery(measurementshare)
                self._trigger.set()

        except Exception as e:
            SetError(f"Failed to process MQTT name/set command: {e}", category='mqtt')

    def on_publish(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_publish: mid: ' + str(mid))

    def on_subscribe(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_subscribe: ' + str(mid) + ' ' + str(reason_codes))

    def on_log(self, mqttc, obj, level, string):
        logger.debug('MQTT on_log: ' + string)

    def _send_global_discovery(self):
        """Send discovery for global entities (Status, Error, Version, etc.)"""
        if not config['mqtt']['discovery']:
            return

        identifier = config['mqtt']['base_topic']
        device_info = {
            "identifiers": [identifier],
            "name": "S0PCM Reader",
            "model": "S0PCM",
            "manufacturer": "SmartMeterDashboard",
            "sw_version": s0pcmreaderversion
        }

        # Status Binary Sensor
        status_unique_id = f"s0pcm_{identifier}_status"
        status_topic = f"{config['mqtt']['discovery_prefix']}/binary_sensor/{identifier}/{status_unique_id}/config"
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

        # Cleanup legacy
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_info/config", "", retain=True)
        self._mqttc.publish(f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/s0pcm_{identifier}_uptime/config", "", retain=True)

        # Error Sensor
        error_unique_id = f"s0pcm_{identifier}_error"
        error_topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{error_unique_id}/config"
        error_payload = {
            "name": "S0PCM Reader Error",
            "unique_id": error_unique_id,
            "device": device_info,
            "entity_category": "diagnostic",
            "state_topic": config['mqtt']['base_topic'] + '/error',
            "icon": "mdi:alert-circle"
        }
        self._mqttc.publish(error_topic, json.dumps(error_payload), retain=True)

        # Diagnostics
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

        self._global_discovery_sent = True
        logger.info('Sent global MQTT discovery messages')

    def _send_meter_discovery(self, meter_id, meter_data):
        """Send discovery for a specific meter."""
        if not config['mqtt']['discovery']:
            return

        identifier = config['mqtt']['base_topic']
        device_info = {"identifiers": [identifier]} # Link to global device
        instancename = meter_data.get('name', str(meter_id))

        for subkey in ['total', 'today', 'yesterday']:
            unique_id = f"s0pcm_{identifier}_{meter_id}_{subkey}"
            topic = f"{config['mqtt']['discovery_prefix']}/sensor/{identifier}/{unique_id}/config"
            
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

            if config['mqtt']['split_topic']:
                payload['state_topic'] = f"{config['mqtt']['base_topic']}/{instancename}/{subkey}"
            else:
                payload['state_topic'] = f"{config['mqtt']['base_topic']}/{instancename}"
                payload['value_template'] = f"{{{{ value_json.{subkey} }}}}"

            # Force refresh
            self._mqttc.publish(topic, "", retain=True)
            self._mqttc.publish(topic, json.dumps(payload), retain=True)

            if subkey == 'total':
                # Text Entity (Name)
                text_uid = f"s0pcm_{identifier}_{meter_id}_name_config"
                text_topic = f"{config['mqtt']['discovery_prefix']}/text/{identifier}/{text_uid}/config"
                text_payload = {
                    "name": f"{instancename} Name",
                    "unique_id": text_uid,
                    "device": device_info,
                    "entity_category": "config",
                    "command_topic": f"{config['mqtt']['base_topic']}/{meter_id}/name/set",
                    "state_topic": f"{config['mqtt']['base_topic']}/{meter_id}/name",
                    "icon": "mdi:tag-text-outline"
                }
                self._mqttc.publish(text_topic, "", retain=True)
                self._mqttc.publish(text_topic, json.dumps(text_payload), retain=True)
                self._mqttc.publish(f"{config['mqtt']['base_topic']}/{meter_id}/name", meter_data.get('name', ""), retain=True)

                # Number Entity (Total Correction)
                num_uid = f"s0pcm_{identifier}_{meter_id}_total_config"
                num_topic = f"{config['mqtt']['discovery_prefix']}/number/{identifier}/{num_uid}/config"
                num_payload = {
                    "name": f"{instancename} Total Correction",
                    "unique_id": num_uid,
                    "device": device_info,
                    "entity_category": "config",
                    "command_topic": f"{config['mqtt']['base_topic']}/{meter_id}/total/set",
                    "state_topic": f"{config['mqtt']['base_topic']}/{meter_id}/total",
                    "min": 0, "max": 2147483647, "step": 1, "mode": "box", "icon": "mdi:counter"
                }
                self._mqttc.publish(num_topic, "", retain=True)
                self._mqttc.publish(num_topic, json.dumps(num_payload), retain=True)
                self._mqttc.publish(f"{config['mqtt']['base_topic']}/{meter_id}/total", meter_data.get('total', 0), retain=True)

        self._discovered_meters[meter_id] = instancename
        logger.info(f"Sent discovery for Meter {meter_id} ({instancename})")

    def send_discovery(self, measurementlocal):
        """Legacy compatibility wrapper - now triggers both global and meter discovery."""
        self._send_global_discovery()
        for mid in measurementlocal:
            if isinstance(mid, int):
                self._send_meter_discovery(mid, measurementlocal[mid])

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
                    self._recover_state() # Perform state recovery
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
        # Persistent Global Date
        current_date = str(measurementlocal.get('date', ""))
        previous_date = str(measurementprevious.get('date', ""))
        if current_date != previous_date:
            self._mqttc.publish(config['mqtt']['base_topic'] + '/date', current_date, retain=True)

        for key in measurementlocal:
            if isinstance(key, int):
                # Filter logic
                if config['s0pcm']['include'] is not None and key not in config['s0pcm']['include']:
                        logger.debug(f"MQTT Publish for input '{key}' is disabled")
                        continue
                if not measurementlocal[key].get('enabled', True):
                        continue

                jsondata = {}
                instancename = measurementlocal[key].get('name', str(key))

                # Internal persistent topics
                for internal_field in ['pulsecount', 'total', 'today', 'yesterday']:
                    if internal_field in measurementlocal[key]:
                        # Always publish ID-based internal topics for recovery, 
                        # but only on change to reduce traffic
                        val = measurementlocal[key][internal_field]
                        old_val = measurementprevious.get(key, {}).get(internal_field)
                        if val != old_val:
                            self._mqttc.publish(f"{config['mqtt']['base_topic']}/{key}/{internal_field}", val, retain=True)

                for subkey in ['total', 'today', 'yesterday']:
                    value_previous = measurementprevious.get(key, {}).get(subkey, -1)
                    
                    try:
                        if subkey in measurementlocal[key]:
                            if config['mqtt']['split_topic'] == True:
                                # On-change check (value and name/topic)
                                if measurementlocal[key][subkey] == value_previous and \
                                   measurementlocal[key].get('name') == measurementprevious.get(key, {}).get('name') and \
                                   config['s0pcm']['publish_onchange'] == True:
                                    continue
                                
                                
                                logger.debug(f"MQTT Publish: topic='{config['mqtt']['base_topic']}/{instancename}/{subkey}', value='{measurementlocal[key][subkey]}'")
                                self._mqttc.publish(config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey, measurementlocal[key][subkey], retain=config['mqtt']['retain'])
                            else:
                                jsondata[subkey] = measurementlocal[key][subkey]

                    except Exception as e:
                        SetError(f"MQTT Publish Failed for {instancename}/{subkey}. {type(e).__name__}: '{str(e)}'", category='mqtt')

                # Publish Name State (for text entity) if name changed
                current_name = measurementlocal[key].get('name', "")
                previous_name = measurementprevious.get(key, {}).get('name', "")
                if current_name != previous_name or not measurementprevious:
                    try:
                        name_topic = f"{config['mqtt']['base_topic']}/{key}/name"
                        logger.debug(f"MQTT Publish Name: topic='{name_topic}', value='{current_name}'")
                        self._mqttc.publish(name_topic, current_name, retain=True)
                    except Exception as e:
                        SetError(f"MQTT Publish Name Failed for {key}. {type(e).__name__}: '{str(e)}'", category='mqtt')

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

            if not self._global_discovery_sent:
                self._send_global_discovery()

            # Dynamic Meter Discovery
            for mid in measurementlocal:
                if isinstance(mid, int):
                    current_name = measurementlocal[mid].get('name', str(mid))
                    if mid not in self._discovered_meters or self._discovered_meters[mid] != current_name:
                        self._send_meter_discovery(mid, measurementlocal[mid])

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
        MigrateData()
        ReadConfig()
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
