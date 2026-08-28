"""Factory functions for creating test configuration models."""

from config import ConfigModel, MqttConfig, SerialConfig


def make_test_config(**mqtt_overrides) -> ConfigModel:
    """Create ConfigModel populated with test defaults."""
    mqtt_defaults = {
        "host": "core-mosquitto",
        "port": 1883,
        "tls_port": 8883,
        "username": "test_user",
        "password": "test_pass",
        "base_topic": "s0pcmreader",
        "client_id": None,
        "version": "5.0",
        "retain": True,
        "split_topic": True,
        "connect_retry": 1,
        "online": "online",
        "offline": "offline",
        "lastwill": "offline",
        "tls": False,
        "tls_ca": "",
        "tls_check_peer": False,
        "discovery": True,
        "discovery_prefix": "homeassistant",
        "recovery_wait": 0,
    }
    mqtt_defaults.update(mqtt_overrides)
    return ConfigModel(
        serial=SerialConfig(),
        mqtt=MqttConfig(**mqtt_defaults),
    )
