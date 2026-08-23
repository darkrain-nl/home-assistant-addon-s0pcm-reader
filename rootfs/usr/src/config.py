"""Configuration loading from options.json and Supervisor API."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
import serialx

from constants import ConnectionStatus
from utils import get_supervisor_config

logger = logging.getLogger(__name__)


class LogConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"


class SerialConfig(BaseModel):
    """Serial port configuration."""

    port: str = "/dev/ttyACM0"
    baudrate: int = 9600
    parity: serialx.Parity = serialx.PARITY_EVEN
    stopbits: serialx.StopBits = serialx.STOPBITS_ONE
    bytesize: int = serialx.SEVENBITS
    timeout: float | None = 30.0
    connect_retry: int = 5


class MqttConfig(BaseModel):
    """MQTT connection and publishing configuration."""

    host: str = "127.0.0.1"
    port: int = 1883
    tls_port: int = 8883
    username: SecretStr | None = None
    password: SecretStr | None = None
    base_topic: str = "s0pcmreader"
    client_id: str | None = None
    version: str = "5.0"
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


def init_args() -> Path:
    """Initialize arguments and global configuration paths."""
    parser = argparse.ArgumentParser(prog="s0pcm-reader", description="S0 Pulse Counter Module")
    # Default to /data in container, local path in dev.
    default_config = "/data" if Path("/data").exists() else "./"
    parser.add_argument(
        "-c", "--config", help="Directory where the configuration resides", type=str, default=default_config
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    return config_path


async def _auto_detect_serial_port() -> str:
    """Auto-detect S0PCM USB serial adapter from available ports."""
    try:
        ports = await asyncio.to_thread(serialx.list_serial_ports)
        if not ports:
            logger.warning("Auto-detect: No serial ports detected. Defaulting to /dev/ttyACM0")
            return "/dev/ttyACM0"

        # Check candidate vendor IDs or driver names.
        for p in ports:
            is_candidate_vid = p.vid in (0x1A86, 0x2341, 0x2A03)

            dev_str = p.device.lower()
            desc_str = p.description.lower() if p.description is not None else ""
            mfg_str = p.manufacturer.lower() if p.manufacturer is not None else ""

            is_candidate_str = any(
                keyword in dev_str or keyword in desc_str or keyword in mfg_str
                for keyword in ("1a86", "arduino", "leonardo")
            )

            if is_candidate_vid or is_candidate_str:
                chip_info = (
                    "CH340" if (p.vid == 0x1A86 or "1a86" in mfg_str or "1a86" in dev_str) else "Arduino/Leonardo"
                )
                logger.info(f"Auto-detect: Found S0PCM candidate device at '{p.device}' ({chip_info})")
                return p.device

        # Fallback to any USB serial port before generic ports.
        for p in ports:
            if "usb" in p.device.lower() or (p.description is not None and "usb" in p.description.lower()):
                logger.info(f"Auto-detect: Selecting first available USB serial port '{p.device}' ({p.description})")
                return p.device

        first_port = ports[0].device
        logger.info(f"Auto-detect: No USB-serial candidate found. Selecting first port '{first_port}'")
        return first_port
    except Exception as e:
        logger.error(f"Auto-detect: Exception during port scan: {e}. Defaulting to /dev/ttyACM0")
        return "/dev/ttyACM0"


async def read_config(
    version: str = "Unknown",
    config_dir: Path = Path("./"),
) -> ConfigModel:
    """Read configuration from options.json or Supervisor."""
    options_path = Path("/data/options.json")
    ha_options = {}

    def _read_options():
        if options_path.exists():
            try:
                return json.loads(options_path.read_text())
            except Exception as e:
                logger.error(f"Failed to load {options_path}: {e}")
        return {}

    ha_options = await asyncio.to_thread(_read_options)

    mqtt_service = {}
    if not ha_options.get("mqtt_host"):
        mqtt_service = await get_supervisor_config("mqtt")
        if mqtt_service:
            logger.info("Using MQTT service discovery for connection settings.")

    mqtt_opts = ha_options.get("mqtt", {})
    adv_opts = ha_options.get("advanced", {})
    sec_opts = ha_options.get("security", {})

    mqtt_version_str = str(mqtt_opts.get("protocol", "5.0"))

    tls_ca = sec_opts.get("tls_ca", "")
    if tls_ca:
        tls_ca_path = Path(tls_ca)
        if not tls_ca_path.is_absolute():
            tls_ca = str(config_dir / tls_ca)

    device_opt = ha_options.get("device")
    resolved_port = await _auto_detect_serial_port() if device_opt in [None, "", "null"] else device_opt

    model = ConfigModel(
        log=LogConfig(level=(ha_options.get("log_level") or "INFO").upper()),
        serial=SerialConfig(port=resolved_port),
        mqtt=MqttConfig(
            host=mqtt_opts.get("host") or mqtt_service.get("host", "127.0.0.1"),
            port=mqtt_opts.get("port") or mqtt_service.get("port", 1883),
            tls_port=sec_opts.get("tls_port", 8883),
            username=mqtt_opts.get("username") or mqtt_service.get("username"),
            password=mqtt_opts.get("password") or mqtt_service.get("password"),
            base_topic=mqtt_opts.get("base_topic", "s0pcmreader"),
            client_id=mqtt_opts.get("client_id") if mqtt_opts.get("client_id") not in [None, "", "None"] else None,
            version=mqtt_version_str,
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

    root_logger = logging.getLogger()
    root_logger.setLevel(model.log.level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setLevel(model.log.level)
    stream.setFormatter(formatter)
    root_logger.addHandler(stream)

    # Suppress serialx byte-level debug logging.
    logging.getLogger("serialx").setLevel(logging.WARNING)

    logger.info(f"Start: s0pcm-reader - version: {version}")

    # Log configuration with sanitized secrets.
    config_log = model.model_dump(mode="json")
    logger.debug(f"Config: {config_log!s}")

    return model
