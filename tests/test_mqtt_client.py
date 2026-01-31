"""
Tests for MQTT client functionality.
"""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

import config as config_module
import s0pcm_reader
import state as state_module


@pytest.fixture(autouse=True)
def setup_mqtt_config():
    # state_module.config/measurement cleared by conftest.py
    context = state_module.get_context()

    # Initialize basic MQTT config using the standard read_config logic
    context.config = config_module.read_config(version="test").model_dump()
    context.s0pcm_reader_version = "dev"

    # Override keys specifically needed for tests
    context.config["mqtt"].update({"base_topic": "s0", "discovery_prefix": "ha", "client_id": None})


@pytest.fixture
def mock_mqtt_client(mocker):
    # Patch the mqtt module in mqtt_handler
    mock_mqtt = mocker.patch("mqtt_handler.mqtt")
    mock_client = MagicMock()
    mock_mqtt.Client.return_value = mock_client
    return mock_client


class TestMQTTConnection:
    def test_mqtt_connect_success(self, mock_mqtt_client, mocker):
        task = s0pcm_reader.TaskDoMQTT(threading.Event(), threading.Event())
        task._mqttc = mock_mqtt_client
        task.on_connect(mock_mqtt_client, None, None, 0, None)
        assert task._connected is True


class TestMQTTPublish:
    def test_publish_measurements(self, mock_mqtt_client):
        context = state_module.get_context()
        context.config["mqtt"]["split_topic"] = True
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client

        # Build proper AppState
        state = state_module.AppState()
        state.meters[1] = state_module.MeterState(name="Water", total=100)

        task._publish_measurements(state, None)
        assert any("s0/Water/total" in str(c) for c in mock_mqtt_client.publish.call_args_list)


class TestStateRecovery:
    def test_recover_state_logic(self, mock_mqtt_client, mocker):
        mocker.patch("time.sleep")
        # Mock StateRecoverer instead of the internal method if possible,
        # or just verify _recover_state calls it.
        # Since we removed the internal logic, we verify the high-level call.
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client

        with patch("mqtt_handler.StateRecoverer") as mock_recoverer:
            task._recover_state()
            assert mock_recoverer.return_value.run.called


class TestMQTTSetCommands:
    def test_handle_set_command(self):
        context = state_module.get_context()
        context.state[1] = state_module.MeterState(total=0)
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._handle_set_command(MagicMock(topic="s0/1/total/set", payload=b"500"))
        assert context.state[1].total == 500

    def test_handle_name_set(self, mock_mqtt_client):
        context = state_module.get_context()
        context.state[1] = state_module.MeterState(total=0)
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client
        task._handle_name_set(MagicMock(topic="s0/1/name/set", payload=b"Kitchen"))
        assert context.state[1].name == "Kitchen"

        # Name clearing
        task._handle_name_set(MagicMock(topic="s0/1/name/set", payload=b""))
        assert context.state[1].name is None


def test_mqtt_handler_error_cases(mocker):
    """Test error handling in MQTT message processing."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    context = state_module.get_context()
    context.state[1] = state_module.MeterState(total=100)

    # 1. Unknown identifier (not ID, not Name)
    context = state_module.get_context()
    with patch.object(context, "set_error") as mock_err:
        task._handle_set_command(MagicMock(topic="s0/UnknownMeter/total/set", payload=b"500"))
        assert mock_err.called
        assert "unknown meter" in str(mock_err.call_args).lower()

    # 2. Invalid payload (non-numeric)
    with patch.object(context, "set_error") as mock_err:
        task._handle_set_command(MagicMock(topic="s0/1/total/set", payload=b"ABC"))
        assert mock_err.called
        assert "invalid payload" in str(mock_err.call_args).lower()

    # 3. Unknown name in set
    with patch.object(context, "set_error") as mock_err:
        task._handle_set_command(MagicMock(topic="s0/NonExistent/total/set", payload=b"500"))
        assert mock_err.called


def test_mqtt_callbacks(mocker):
    """Test standard MQTT callbacks."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    task._mqttc = MagicMock()

    # on_connect failure
    context = state_module.get_context()
    with patch.object(context, "set_error") as mock_set:
        task.on_connect(None, None, None, 5, None)  # 5 is unauthorized
        assert mock_set.called

    # on_disconnect
    task.on_disconnect(None, None, None, 0, None)
    assert not task._connected


def test_publish_measurements_json(mocker):
    """Test MQTT publication in JSON mode (split_topic=False)."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    context = state_module.get_context()
    context.config["mqtt"]["split_topic"] = False
    context.config["mqtt"]["base_topic"] = "s0"
    context.config["mqtt"]["retain"] = True

    task._mqttc = MagicMock()

    state = state_module.AppState()
    state.meters[1] = state_module.MeterState(name="Water", total=100, today=5, yesterday=2)

    task._publish_measurements(state, None)

    # Check if JSON was published to s0/Water
    json_call = [c for c in task._mqttc.publish.call_args_list if "s0/Water" in str(c)]
    assert json_call
    payload = json.loads(json_call[0][0][1])
    assert payload["total"] == 100
    assert payload["today"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
