"""
Tests for MQTT edge cases in TaskDoMQTT.
"""

from unittest.mock import MagicMock, patch

import pytest

from mqtt_handler import TaskDoMQTT
import state as state_module


@pytest.fixture
def mqtt_task():
    trigger = MagicMock()
    stopper = MagicMock()
    # Ensure context is reset
    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "base_topic": "s0pcm",
            "online": "online",
            "offline": "offline",
            "retain": True,
            "client_id": "test_client",
            "version": 4,  # MQTTv311
            "username": "user",
            "password": "pass",
            "tls": False,
            "tls_ca": "",
            "tls_check_peer": False,
            "tls_port": 8883,
            "port": 1883,
            "host": "localhost",
            "connect_retry": 0.1,
            "lastwill": "offline",
            "discovery": True,
            "discovery_prefix": "homeassistant",
        }
    }
    return TaskDoMQTT(trigger, stopper)


def test_on_connect_failed(mqtt_task):
    """Test on_connect with a failure reason code."""
    context = state_module.get_context()
    mqtt_task.on_connect(None, None, None, 5, None)  # 5 = Connection refused - not authorized

    assert mqtt_task._connected is False
    assert "MQTT failed to connect to broker" in context.lasterror_share


def test_on_disconnect_unexpected(mqtt_task):
    """Test on_disconnect with a non-zero reason code."""
    context = state_module.get_context()
    mqtt_task._connected = True
    mqtt_task.on_disconnect(None, None, None, 1, None)  # 1 = Unspecified error

    assert mqtt_task._connected is False
    assert "MQTT failed to disconnect from broker" in context.lasterror_share


def test_setup_mqtt_client_tls_ca_error(mqtt_task):
    """Test MQTT client setup with an invalid TLS CA file path."""
    context = state_module.get_context()
    context.config["mqtt"]["tls"] = True
    context.config["mqtt"]["tls_ca"] = "/non/existent/path/ca.crt"

    # Mock ssl.SSLContext.load_verify_locations to raise an error
    with patch("ssl.SSLContext.load_verify_locations", side_effect=Exception("File not found")):
        result = mqtt_task._setup_mqtt_client(use_tls=True)
        assert result is False
        assert "Failed to load TLS CA file" in context.lasterror_share


def test_connect_loop_timeout(mqtt_task):
    """Test connection loop when it times out waiting for CONNACK."""
    context = state_module.get_context()
    mqtt_task._stopper.is_set.side_effect = [False, True]  # Loop once then stop

    with (
        patch("mqtt_handler.mqtt.Client"),
        patch("time.sleep"),
        patch("time.time", side_effect=[100.0, 115.0, 116.0, 117.0, 118.0]),
    ):
        mqtt_task._connect_loop()
        assert "MQTT connection failed: Timeout waiting for MQTT CONNACK" in context.lasterror_share


def test_connect_loop_tls_fallback(mqtt_task):
    """Test connection loop falling back from TLS to plain MQTT on failure."""
    context = state_module.get_context()
    context.config["mqtt"]["tls"] = True
    mqtt_task._stopper.is_set.side_effect = [False, False, True]  # Loop twice then stop

    mock_client = MagicMock()

    with patch("mqtt_handler.mqtt.Client", return_value=mock_client), patch("time.sleep"):
        # First connect raises error, triggering fallback
        # Second connect needs to simulate success by setting _connected = True
        def connect_side_effect(*args, **kwargs):
            if connect_side_effect.called == 0:
                connect_side_effect.called += 1
                raise Exception("TLS Error")
            mqtt_task._connected = True
            return 0

        connect_side_effect.called = 0
        mock_client.connect.side_effect = connect_side_effect

        mqtt_task._connect_loop()

        assert "MQTT TLS failed: TLS Error. Falling back to plain." in context.lasterror_share
        # Verify it attempted to reconnect without TLS (or at least set use_tls=False internally)
        # Note: use_tls is local to _connect_loop, but we see the side effect in context errors.
