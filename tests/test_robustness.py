"""
Tests for previously uncovered edge cases in MQTT, HA API recovery, and discovery.
"""

import json
import ssl
from unittest.mock import MagicMock, patch

import paho.mqtt.client as mqtt
import pytest

import discovery
from mqtt_handler import TaskDoMQTT
from recovery import StateRecoverer
import state as state_module


@pytest.fixture
def mock_context():
    context = state_module.get_context()
    with context.lock:
        context.config = {
            "mqtt": {
                "host": "127.0.0.1",
                "port": 1883,
                "tls_port": 8883,
                "username": "user",
                "password": "pass",
                "base_topic": "test",
                "client_id": "test_client",
                "version": mqtt.MQTTv5,
                "tls": False,
                "tls_ca": "",
                "tls_check_peer": False,
                "lastwill": "offline",
                "retain": True,
                "split_topic": True,
                "connect_retry": 1,
                "online": "online",
                "discovery": True,
                "discovery_prefix": "homeassistant",
            },
            "serial": {"port": "COM1", "baudrate": 9600},
        }

    # Patch get_context in all modules where it might be used
    with (
        patch("state.get_context", return_value=context),
        patch("mqtt_handler.state_module.get_context", return_value=context),
        patch("recovery.state_module.get_context", return_value=context),
        patch("discovery.state_module.get_context", return_value=context),
    ):
        yield context


# --- MQTT TLS & Fallback Tests ---


def test_mqtt_setup_tls_ca_error(mock_context):
    """Test MQTT setup fails if CA file is invalid."""
    mock_context.config["mqtt"]["tls"] = True
    mock_context.config["mqtt"]["tls_ca"] = "/nonexistent/ca.crt"

    trigger = MagicMock()
    stopper = MagicMock()
    task = TaskDoMQTT(trigger, stopper)

    # Mock ssl.SSLContext to avoid real file operations
    with patch("ssl.SSLContext.load_verify_locations", side_effect=Exception("File not found")):
        success = task._setup_mqtt_client(use_tls=True)
        assert success is False
        assert "Failed to load TLS CA file" in str(mock_context.lasterror_mqtt)


def test_mqtt_setup_tls_check_peer(mock_context):
    """Test TLS setup with check_peer enabled."""
    mock_context.config["mqtt"]["tls"] = True
    mock_context.config["mqtt"]["tls_ca"] = "/tmp/fake_ca.crt"
    mock_context.config["mqtt"]["tls_check_peer"] = True

    trigger = MagicMock()
    stopper = MagicMock()
    task = TaskDoMQTT(trigger, stopper)

    with patch("ssl.SSLContext.load_verify_locations"):
        with patch("ssl.SSLContext") as mock_ssl_context:
            instance = mock_ssl_context.return_value
            task._setup_mqtt_client(use_tls=True)
            assert instance.verify_mode == ssl.CERT_REQUIRED
            assert instance.check_hostname is True


@patch("time.sleep")  # Speed up test
def test_mqtt_connect_loop_fallback(mock_sleep, mock_context):
    """Test MQTT fallback from TLS to plain on connection failure."""
    mock_context.config["mqtt"]["tls"] = True

    trigger = MagicMock()
    stopper = MagicMock()
    # Signal stopper after fallback attempt to prevent infinite loop
    stopper.is_set.side_effect = [False, False, True]

    task = TaskDoMQTT(trigger, stopper)
    mock_mqttc = MagicMock()

    def side_effect_setup(use_tls_call):
        task._mqttc = mock_mqttc
        # Simulate connection success for the fallback attempt
        task._connected = True
        return True

    with patch.object(task, "_setup_mqtt_client", side_effect=side_effect_setup):
        # Patch the context in both places where it might be cached
        with patch("mqtt_handler.state_module.get_context", return_value=mock_context):
            # First call fails (TLS), second call succeeds (Plain)
            mock_mqttc.connect.side_effect = [Exception("TLS Handshake Failed"), 0]

            task._connect_loop()

            # Verify first error was set
            assert "MQTT TLS failed" in str(mock_context.lasterror_mqtt)
            # Verify fallback port was used (1883)
            mock_mqttc.connect.assert_any_call(mock_context.config["mqtt"]["host"], 1883, 60)
            assert mock_mqttc.connect.call_count == 2


# --- HA API Error Tests ---


def test_recovery_ha_api_no_token(mock_context):
    """Test HA recovery skips if token is missing."""
    with patch("os.getenv", return_value=None):
        recoverer = StateRecoverer(MagicMock())
        state = recoverer.fetch_ha_state("sensor.test")
        assert state is None
        states = recoverer.fetch_all_ha_states()
        assert states == []


def test_recovery_ha_api_http_error(mock_context):
    """Test HA recovery handles HTTP errors."""
    with patch("os.getenv", return_value="fake_token"):
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.return_value.__enter__.return_value.status = 500
            recoverer = StateRecoverer(MagicMock())
            state = recoverer.fetch_ha_state("sensor.test")
            assert state is None


# --- State Recovery Edge Cases ---


def test_recovery_on_message_invalid_date(mock_context):
    """Test recovery ignores invalid date formats."""
    recoverer = StateRecoverer(MagicMock())
    msg = MagicMock()
    msg.topic = "test/date"
    msg.payload = b"invalid-date"

    old_date = mock_context.state.date
    recoverer.on_message(None, None, msg)
    assert mock_context.state.date == old_date


def test_recovery_find_total_localized_numbers(mock_context):
    """Test HA recovery parsing of various number formats."""
    recoverer = StateRecoverer(MagicMock())
    with mock_context.lock:
        mock_context.state.meters[1] = state_module.MeterState()

    test_cases = [
        ("1.000,50 m3", 1000),
        ("1,234.56 kWh", 1234),
        ("500 L", 500),
        ("Unavailable", None),
        ("1.234.567", 1234567),  # Triple dot cleaning
        ("1,000,000.00", 1000000),  # US mixed
    ]

    for input_str, expected in test_cases:
        ha_states = [{"entity_id": "sensor.test_1_total", "state": input_str}]
        val = recoverer._find_total_in_ha(1, ha_states)
        assert val == expected


# --- Discovery Tests ---


def test_send_meter_discovery_combined_topic(mock_context):
    """Test discovery payload when split_topic is False."""
    mock_context.config["mqtt"]["split_topic"] = False
    mock_mqtt = MagicMock()

    discovery.send_meter_discovery(mock_mqtt, 1, {"name": "Combined"})

    # Check if value_template is correctly set in one of the publish calls
    found_template = False
    for call in mock_mqtt.publish.call_args_list:
        payload_str = call.args[1]
        if payload_str:
            payload = json.loads(payload_str)
            if "value_template" in payload and "{{ value_json.total }}" in payload["value_template"]:
                found_template = True
                break
    assert found_template is True
