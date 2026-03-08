"""
S0PCM Reader Configuration

Handles command-line argument parsing and configuration loading from
Home Assistant options.json and Supervisor API.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from pydantic import BaseModel, Field
import serial

from constants import ConnectionStatus
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
    timeout: float | None = None
    connect_retry: int = 5


class MqttConfig(BaseModel):
    """MQTT connection and publishing configuration."""

    host: str = "127.0.0.1"
    port: int = 1883
    tls_port: int = 8883
    username: str | None = None
    password: str | None = None
    base_topic: str = "s0pcmreader"
    client_id: str | None = None
    version: Any = mqtt.MQTTv5
    retain: bool = True
    split_topic: bool = True
    connect_retry: int = 5
    online: str = ConnectionStatus.ONLINE
    offline: str = ConnectionStatus.OFFLINE
    lastwill: str = ConnectionStatus.OFFLINE
    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    tls: bool = False
    tls_ca: str = ""
    tls_check_peer: bool = False
    recovery_wait: int = 7


class ConfigModel(BaseModel):
    """Root configuration model."""

    log: LogConfig = Field(default_factory=LogConfig)
    serial: SerialConfig = Field(default_factory=SerialConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)


# ------------------------------------------------------------------------------------
# Configuration Paths
# ------------------------------------------------------------------------------------


def init_args() -> Path:
    """Initialize arguments and global configuration paths."""
    parser = argparse.ArgumentParser(prog="s0pcm-reader", description="S0 Pulse Counter Module")
    # Determine default config directory: /data for HA, ./ for local dev
    default_config = "/data" if Path("/data").exists() else "./"
    parser.add_argument(
        "-c", "--config", help="Directory where the configuration resides", type=str, default=default_config
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    return config_path


def read_config(
    version: str = "Unknown",
    config_dir: Path = Path("./"),
) -> ConfigModel:
    """
    Read and populate the configuration.

    Args:
        version: The app version string for logging
        config_dir: Directory where config files reside

    Returns:
        ConfigModel: The populated configuration object
    """
    # 1. Load Home Assistant Options
    options_path = Path("/data/options.json")
    ha_options = {}
    if options_path.exists():
        try:
            ha_options = json.loads(options_path.read_text())
        except Exception as e:
            logger.error(f"Failed to load {options_path}: {e}")

    # 2. MQTT Service Discovery
    mqtt_service = {}
    if not ha_options.get("mqtt_host"):
        mqtt_service = get_supervisor_config("mqtt")
        if mqtt_service:
            logger.info("Using MQTT service discovery for connection settings.")

    # 3. Build Config Model
    mqtt_opts = ha_options.get("mqtt", {})
    adv_opts = ha_options.get("advanced", {})
    sec_opts = ha_options.get("security", {})

    mqtt_version_str = str(mqtt_opts.get("protocol", "5.0"))
    version_map = {"3.1": mqtt.MQTTv31, "3.1.1": mqtt.MQTTv311, "5.0": mqtt.MQTTv5}
    mqtt_version = version_map.get(mqtt_version_str, mqtt.MQTTv5)

    tls_ca = sec_opts.get("tls_ca", "")
    if tls_ca:
        tls_ca_path = Path(tls_ca)
        if not tls_ca_path.is_absolute():
            tls_ca = str(config_dir / tls_ca)

    model = ConfigModel(
        log=LogConfig(level=(ha_options.get("log_level") or "INFO").upper()),
        serial=SerialConfig(port=ha_options.get("device", "/dev/ttyACM0")),
        mqtt=MqttConfig(
            host=mqtt_opts.get("host") or mqtt_service.get("host", "127.0.0.1"),
            port=mqtt_opts.get("port") or mqtt_service.get("port", 1883),
            tls_port=sec_opts.get("tls_port", 8883),
            username=mqtt_opts.get("username") or mqtt_service.get("username"),
            password=mqtt_opts.get("password") or mqtt_service.get("password"),
            base_topic=mqtt_opts.get("base_topic", "s0pcmreader"),
            client_id=mqtt_opts.get("client_id") if mqtt_opts.get("client_id") not in [None, "", "None"] else None,
            version=mqtt_version,
            retain=adv_opts.get("retain", True),
            split_topic=adv_opts.get("split_topic", True),
            discovery=adv_opts.get("discovery", True),
            discovery_prefix=adv_opts.get("discovery_prefix", "homeassistant"),
            tls=sec_opts.get("tls", False),
            tls_ca=tls_ca,
            tls_check_peer=sec_opts.get("tls_check_peer", False),
            recovery_wait=adv_opts.get("recovery_wait", 7),
        ),
    )

    # 4. Global Logging Setup
    root_logger = logging.getLogger()
    root_logger.setLevel(model.log.level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setLevel(model.log.level)
    stream.setFormatter(formatter)
    root_logger.addHandler(stream)

    logger.info(f"Start: s0pcm-reader - version: {version}")

    # Debug logging with redacted sensitive info
    config_log = model.model_dump()
    config_log["mqtt"]["password"] = "********"  # noqa: S105
    config_log["mqtt"]["username"] = "********"
    logger.debug(f"Config: {config_log!s}")

    return model
