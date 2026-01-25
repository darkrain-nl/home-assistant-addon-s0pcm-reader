"""
S0PCM Reader Configuration

Handles command-line argument parsing and configuration loading from
Home Assistant options.json and Supervisor API.
"""

import argparse
import copy
import json
import logging
import os
from pathlib import Path

import serial
import paho.mqtt.client as mqtt

from utils import GetSupervisorConfig

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------
# Configuration Paths
# ------------------------------------------------------------------------------------
configdirectory = './'
measurementname = 'measurement.json'


def init_args():
    """
    Initialize arguments and global configuration paths.
    
    Parses command line arguments and sets configdirectory and measurementname.
    """
    global configdirectory, measurementname
    
    parser = argparse.ArgumentParser(
        prog='s0pcm-reader', 
        description='S0 Pulse Counter Module', 
        epilog='...'
    )
    # Determine default config directory: /data for HA, ./ for local dev
    default_config = '/data' if os.path.exists('/data') else './'
    parser.add_argument(
        '-c', '--config', 
        help='Directory where the configuration resides', 
        type=str, 
        default=default_config
    )
    args = parser.parse_args()

    configdirectory = args.config
    if not configdirectory.endswith('/'):
        configdirectory += '/'
    
    measurementname = configdirectory + 'measurement.json'


def init_defaults():
    """Initialize default paths when running as imported module (e.g., in tests)."""
    global configdirectory, measurementname
    
    if os.path.exists('/data'):
        configdirectory = '/data/'
    else:
        configdirectory = './'
    measurementname = configdirectory + 'measurement.json'


def read_config(config, version):
    """
    Read and populate the configuration dictionary.
    
    Args:
        config: The configuration dictionary to populate (modified in-place)
        version: The addon version string for logging
        
    Returns:
        The populated config dictionary
    """
    config.clear()

    # 1. Load Home Assistant Options
    options_path = Path('/data/options.json')
    ha_options = {}
    if options_path.exists():
        try:
            ha_options = json.loads(options_path.read_text())
        except Exception as e:
            logger.error(f"Failed to load {options_path}: {e}")

    # 2. MQTT Service Discovery (if host not manually provided)
    mqtt_service = {}
    if not ha_options.get('mqtt_host'):
        mqtt_service = GetSupervisorConfig('mqtt')
        if mqtt_service:
            logger.info("Using MQTT service discovery for connection settings.")

    # 3. Define structured configuration with defaults and overrides
    config.update({
        'log': {
            'level': (ha_options.get('log_level') or 'INFO').upper()
        },
        'serial': {
            'port': ha_options.get('device', '/dev/ttyACM0'),
            'baudrate': 9600,
            'parity': serial.PARITY_EVEN,
            'stopbits': serial.STOPBITS_ONE,
            'bytesize': serial.SEVENBITS,
            'timeout': None,
            'connect_retry': 5
        },
        'mqtt': {
            'host': ha_options.get('mqtt_host') or mqtt_service.get('host', '127.0.0.1'),
            'port': ha_options.get('mqtt_port') or mqtt_service.get('port', 1883),
            'tls_port': ha_options.get('mqtt_tls_port', 8883),
            'username': ha_options.get('mqtt_username') or mqtt_service.get('username'),
            'password': ha_options.get('mqtt_password') or mqtt_service.get('password'),
            'base_topic': ha_options.get('mqtt_base_topic', 's0pcmreader'),
            'client_id': ha_options.get('mqtt_client_id') if ha_options.get('mqtt_client_id') not in [None, "", "None"] else None,
            'version': ha_options.get('mqtt_protocol', '5.0'),
            'retain': ha_options.get('mqtt_retain', True),
            'split_topic': ha_options.get('mqtt_split_topic', True),
            'connect_retry': 5,
            'online': 'online',
            'offline': 'offline',
            'lastwill': 'offline',
            'discovery': ha_options.get('mqtt_discovery', True),
            'discovery_prefix': ha_options.get('mqtt_discovery_prefix', 'homeassistant'),
            'tls': ha_options.get('mqtt_tls', False),
            'tls_ca': ha_options.get('mqtt_tls_ca', ''),
            'tls_check_peer': ha_options.get('mqtt_tls_check_peer', False)
        },
        's0pcm': {}
    })

    # 4. Global Logging Setup (Root Logger)
    # This ensuring that all modules (serial_handler, mqtt_handler, etc.) inherit settings
    root_logger = logging.getLogger()
    root_logger.setLevel(config['log']['level'])
    
    # Standardize format (Supervisor timestamps may not appear in all environments)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setLevel(config['log']['level'])
    stream.setFormatter(formatter)
    root_logger.addHandler(stream)

    # 5. Post-processing: Mapping and Path Resolution
    version_map = {'3.1': mqtt.MQTTv31, '3.1.1': mqtt.MQTTv311, '5.0': mqtt.MQTTv5}
    config['mqtt']['version'] = version_map.get(str(config['mqtt']['version']), mqtt.MQTTv5)

    if config['mqtt']['tls_ca'] and not config['mqtt']['tls_ca'].startswith('/'):
        config['mqtt']['tls_ca'] = str(Path(configdirectory) / config['mqtt']['tls_ca'])

    logger.info(f'Start: s0pcm-reader - version: {version}')
    
    # Debug logging with redacted password
    config_log = copy.deepcopy(config)
    if 'mqtt' in config_log and config_log['mqtt'].get('password'):
        config_log['mqtt']['password'] = '********'
    logger.debug(f'Config: {str(config_log)}')
    
    return config


# Backwards compatibility alias
ReadConfig = read_config
