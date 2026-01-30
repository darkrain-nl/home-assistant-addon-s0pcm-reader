"""
S0PCM Reader Configuration

Handles command-line argument parsing and configuration loading from
Home Assistant options.json and Supervisor API.
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

import serial
import paho.mqtt.client as mqtt
from pydantic import BaseModel, Field

from utils import get_supervisor_config

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------
# Configuration Models
# ------------------------------------------------------------------------------------

class LogConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"


class SerialConfig(BaseModel):
    """Serial port configuration."""
    port: str = "/dev/ttyACM0"
    baudrate: int = 9600
    parity: str = serial.PARITY_EVEN
    stopbits: int = serial.STOPBITS_ONE
    bytesize: int = serial.SEVENBITS
    timeout: Optional[float] = None
    connect_retry: int = 5


class MqttConfig(BaseModel):
    """MQTT connection and publishing configuration."""
    host: str = "127.0.0.1"
    port: int = 1883
    tls_port: int = 8883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "s0pcmreader"
    client_id: Optional[str] = None
    version: Any = mqtt.MQTTv5
    retain: bool = True
    split_topic: bool = True
    connect_retry: int = 5
    online: str = "online"
    offline: str = "offline"
    lastwill: str = "offline"
    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    tls: bool = False
    tls_ca: str = ""
    tls_check_peer: bool = False


class ConfigModel(BaseModel):
    """Root configuration model."""
    log: LogConfig = Field(default_factory=LogConfig)
    serial: SerialConfig = Field(default_factory=SerialConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)


# ------------------------------------------------------------------------------------
# Configuration Paths
# ------------------------------------------------------------------------------------
configdirectory = './'


def init_args():
    """Initialize arguments and global configuration paths."""
    global configdirectory
    
    parser = argparse.ArgumentParser(
        prog='s0pcm-reader', 
        description='S0 Pulse Counter Module'
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




def read_config(config_dict: Optional[Dict[str, Any]] = None, version: str = "Unknown") -> ConfigModel:
    """
    Read and populate the configuration.
    
    Args:
        config_dict: Optional dictionary to populate (for backwards compatibility)
        version: The app version string for logging
        
    Returns:
        ConfigModel: The populated configuration object
    """
    # 1. Load Home Assistant Options
    options_path = Path('/data/options.json')
    ha_options = {}
    if options_path.exists():
        try:
            ha_options = json.loads(options_path.read_text())
        except Exception as e:
            logger.error(f"Failed to load {options_path}: {e}")

    # 2. MQTT Service Discovery
    mqtt_service = {}
    if not ha_options.get('mqtt_host'):
        mqtt_service = get_supervisor_config('mqtt')
        if mqtt_service:
            logger.info("Using MQTT service discovery for connection settings.")

    # 3. Build Config Model
    mqtt_version_str = str(ha_options.get('mqtt_protocol', '5.0'))
    version_map = {'3.1': mqtt.MQTTv31, '3.1.1': mqtt.MQTTv311, '5.0': mqtt.MQTTv5}
    mqtt_version = version_map.get(mqtt_version_str, mqtt.MQTTv5)

    tls_ca = ha_options.get('mqtt_tls_ca', '')
    if tls_ca and not tls_ca.startswith('/'):
        tls_ca = str(Path(configdirectory) / tls_ca)

    model = ConfigModel(
        log=LogConfig(
            level=(ha_options.get('log_level') or 'INFO').upper()
        ),
        serial=SerialConfig(
            port=ha_options.get('device', '/dev/ttyACM0')
        ),
        mqtt=MqttConfig(
            host=ha_options.get('mqtt_host') or mqtt_service.get('host', '127.0.0.1'),
            port=ha_options.get('mqtt_port') or mqtt_service.get('port', 1883),
            tls_port=ha_options.get('mqtt_tls_port', 8883),
            username=ha_options.get('mqtt_username') or mqtt_service.get('username'),
            password=ha_options.get('mqtt_password') or mqtt_service.get('password'),
            base_topic=ha_options.get('mqtt_base_topic', 's0pcmreader'),
            client_id=ha_options.get('mqtt_client_id') if ha_options.get('mqtt_client_id') not in [None, "", "None"] else None,
            version=mqtt_version,
            retain=ha_options.get('mqtt_retain', True),
            split_topic=ha_options.get('mqtt_split_topic', True),
            discovery=ha_options.get('mqtt_discovery', True),
            discovery_prefix=ha_options.get('mqtt_discovery_prefix', 'homeassistant'),
            tls=ha_options.get('mqtt_tls', False),
            tls_ca=tls_ca,
            tls_check_peer=ha_options.get('mqtt_tls_check_peer', False)
        )
    )

    # 4. Global Logging Setup
    root_logger = logging.getLogger()
    root_logger.setLevel(model.log.level)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setLevel(model.log.level)
    stream.setFormatter(formatter)
    root_logger.addHandler(stream)

    # 5. Backwards compatibility: populate dictionary
    if config_dict is not None:
        config_dict.clear()
        config_dict.update(model.model_dump())
        # Restore version object (pydantic will have dumped it as int/str potentially)
        config_dict['mqtt']['version'] = model.mqtt.version

    logger.info(f'Start: s0pcm-reader - version: {version}')
    
    # Debug logging with redacted password
    config_log = model.model_dump()
    if config_log['mqtt'].get('password'):
        config_log['mqtt']['password'] = '********'
    logger.debug(f'Config: {str(config_log)}')
    
    return model


