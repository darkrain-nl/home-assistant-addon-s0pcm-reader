"""
Targeted tests for remaining coverage gaps in mqtt_handler.py.
"""

from unittest.mock import MagicMock, patch

import pytest

from mqtt_handler import TaskDoMQTT
import state as state_module


@pytest.fixture
def mqtt_task():
    trigger = MagicMock()
    stopper = MagicMock()
    # Default to not set
    stopper.is_set.return_value = False

    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "base_topic": "s0pcm",
            "online": "online",
            "offline": "offline",
            "retain": True,
            "client_id": "test",
            "version": 4,
            "username": "user",
            "password": "pass",
            "tls": False,
            "tls_ca": "",
            "tls_check_peer": False,
            "tls_port": 8883,
            "port": 1883,
            "host": "localhost",
            "connect_retry": 0.01,
            "discovery": True,
            "discovery_prefix": "homeassistant",
            "split_topic": False,
            "lastwill": "offline",
        }
    }
    context.lasterror_share = None
    context.state_share.reset_state()
    return TaskDoMQTT(trigger, stopper)


def test_handle_set_command_exception(mqtt_task):
    """Test exception handling in _handle_set_command (lines 129-130)."""
    context = state_module.get_context()
    msg = MagicMock()
    msg.topic = None
    mqtt_task._handle_set_command(msg)
    assert context.lasterror_share is not None
    assert "Failed to process MQTT set command" in context.lasterror_share


def test_handle_name_set_exception(mqtt_task):
    """Test exception handling in _handle_name_set (lines 172-173)."""
    context = state_module.get_context()
    msg = MagicMock()
    msg.topic = None
    mqtt_task._handle_name_set(msg)
    assert context.lasterror_share is not None
    assert "Failed to process MQTT name/set command" in context.lasterror_share


def test_publish_diagnostics_exception(mqtt_task):
    """Test exception handling in _publish_diagnostics (lines 282-283)."""
    mqtt_task._mqttc = MagicMock()
    mqtt_task._mqttc.publish.side_effect = Exception("Publish error")
    with patch("mqtt_handler.logger.error") as mock_logger:
        mqtt_task._publish_diagnostics()
        assert mock_logger.called
        assert "Failed to publish info state to MQTT" in mock_logger.call_args[0][0]


def test_main_loop_error_publish_exception(mqtt_task):
    """Test exception handling in _main_loop when publishing errors (lines 381-382)."""
    mqtt_task._connected = True
    mqtt_task._mqttc = MagicMock()

    def side_effect(topic, *args, **kwargs):
        if "/error" in topic:
            raise Exception("Error topic failure")
        return MagicMock()

    mqtt_task._mqttc.publish.side_effect = side_effect
    mqtt_task._global_discovery_sent = True

    # Run loop once
    def is_set_side_effect():
        if is_set_side_effect.called:
            return True
        is_set_side_effect.called = True
        return False

    is_set_side_effect.called = False
    mqtt_task._stopper.is_set.side_effect = is_set_side_effect

    mqtt_task.app_context.lasterror_share = "Some Error"

    with patch("mqtt_handler.logger.error") as mock_logger:
        mqtt_task._main_loop()
        assert mock_logger.called
        assert "MQTT Publish Failed for error" in mock_logger.call_args[0][0]


def test_run_fatal_exception(mqtt_task, mocker):
    """Test fatal exception handling in run() (lines 404-405)."""
    mocker.patch.object(mqtt_task, "_connect_loop", side_effect=Exception("Fatal Run Error"))
    # Ensure it exits loop after first call
    mqtt_task._stopper.is_set.return_value = False

    with patch("mqtt_handler.logger.error") as mock_logger:
        mqtt_task.run()
        assert mock_logger.called
        assert "Fatal MQTT exception" in mock_logger.call_args[0][0]
        assert mqtt_task._stopper.set.called


def test_setup_mqtt_client_tls_empty_ca(mqtt_task, mocker):
    """Test _setup_mqtt_client with TLS enabled but empty CA (lines 191-193)."""
    mqtt_task.app_context.config["mqtt"]["tls"] = True
    mqtt_task.app_context.config["mqtt"]["tls_ca"] = ""
    mock_ssl_context = MagicMock()
    mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)
    result = mqtt_task._setup_mqtt_client(use_tls=True)
    assert result is True


def test_connect_loop_setup_failure(mqtt_task):
    """Test _connect_loop when _setup_mqtt_client fails (lines 225-226)."""

    # Exits loop safely
    def is_set_side_effect():
        if is_set_side_effect.called:
            return True
        is_set_side_effect.called = True
        return False

    is_set_side_effect.called = False
    mqtt_task._stopper.is_set.side_effect = is_set_side_effect

    with patch.object(mqtt_task, "_setup_mqtt_client", return_value=False), patch("time.sleep") as mock_sleep:
        mqtt_task._connect_loop()
        assert mock_sleep.called


def test_publish_measurements_disabled_meter(mqtt_task):
    """Test _publish_measurements skip disabled meter (line 298)."""
    mqtt_task._mqttc = MagicMock()
    state_snapshot = state_module.AppState()
    state_snapshot.meters[1] = state_module.MeterState(enabled=True, total=100)
    state_snapshot.meters[2] = state_module.MeterState(enabled=False, total=200)
    mqtt_task._publish_measurements(state_snapshot, None)
    published_topics = [call.args[0] for call in mqtt_task._mqttc.publish.call_args_list]
    assert any("/1/" in topic for topic in published_topics)
    assert not any("/2/" in topic for topic in published_topics)


def test_run_loop_finally_reconnect(mqtt_task, mocker):
    """Test the cleanup and potentially the loop structure in run() (lines 389-408)."""
    mqtt_task._stopper.is_set.side_effect = [False, True, True, True, True]

    mocker.patch.object(mqtt_task, "_connect_loop")
    mocker.patch.object(mqtt_task, "_main_loop")

    mock_mqttc = MagicMock()
    mqtt_task._mqttc = mock_mqttc
    mqtt_task._connected = True

    mqtt_task.run()

    assert mock_mqttc.publish.called
    assert mock_mqttc.loop_stop.called
    assert mock_mqttc.disconnect.called
    assert mqtt_task._mqttc is None


def test_on_message_dispatch(mqtt_task):
    """Test on_message dispatching to handlers (lines 86-90)."""
    mqtt_task._handle_set_command = MagicMock()
    mqtt_task._handle_name_set = MagicMock()

    msg_set = MagicMock()
    msg_set.topic = "s0pcm/1/total/set"
    mqtt_task.on_message(None, None, msg_set)
    mqtt_task._handle_set_command.assert_called_once_with(msg_set)

    msg_name = MagicMock()
    msg_name.topic = "s0pcm/1/name/set"
    mqtt_task.on_message(None, None, msg_name)
    mqtt_task._handle_name_set.assert_called_once_with(msg_name)


def test_handle_set_command_create_meter(mqtt_task):
    """Test _handle_set_command creating a meter if it doesn't exist (line 124)."""
    context = state_module.get_context()
    context.state.meters = {}

    msg = MagicMock()
    msg.topic = "s0pcm/5/total/set"
    msg.payload = b"1000"

    mqtt_task._handle_set_command(msg)

    assert 5 in context.state.meters
    assert context.state.meters[5].total == 1000


def test_handle_name_set_by_name(mqtt_task, mocker):
    """Test _handle_name_set using name identifier (lines 141-145)."""
    context = state_module.get_context()
    context.state.meters[3] = state_module.MeterState(name="Gas")

    mocker.patch("mqtt_handler.discovery.send_global_discovery")
    mocker.patch("mqtt_handler.discovery.send_meter_discovery")

    msg = MagicMock()
    msg.topic = "s0pcm/Gas/name/set"
    msg.payload = b"NewGasName"

    mqtt_task._handle_name_set(msg)

    assert context.state.meters[3].name == "NewGasName"


def test_handle_name_set_unknown_identifier(mqtt_task):
    """Test _handle_name_set with unknown identifier (lines 148-149)."""
    context = state_module.get_context()
    context.lasterror_share = None

    msg = MagicMock()
    msg.topic = "s0pcm/Unknown/name/set"
    msg.payload = b"ignored"

    mqtt_task._handle_name_set(msg)

    assert context.lasterror_share is not None
    assert "Ignored name/set command for unknown meter" in context.lasterror_share


def test_handle_name_set_create_meter(mqtt_task, mocker):
    """Test _handle_name_set creating a meter (line 159)."""
    context = state_module.get_context()
    context.state.meters = {}

    mocker.patch("mqtt_handler.discovery.send_global_discovery")
    mocker.patch("mqtt_handler.discovery.send_meter_discovery")

    msg = MagicMock()
    msg.topic = "s0pcm/2/name/set"
    msg.payload = b"NewMeter"

    mqtt_task._handle_name_set(msg)

    assert 2 in context.state.meters
    assert context.state.meters[2].name == "NewMeter"


def test_connect_loop_wait_sleep(mqtt_task, mocker):
    """Test _connect_loop sleep during wait for connection (line 237)."""
    mqtt_task._mqttc = MagicMock()
    start_time = 1000.0
    mocker.patch("time.time", side_effect=[start_time, start_time + 1, start_time + 2])
    mqtt_task._stopper.is_set.side_effect = [False, False, True]

    with patch("time.sleep") as mock_sleep:
        mqtt_task._connected = False

        def sleep_side_effect(duration):
            mqtt_task._connected = True

        mock_sleep.side_effect = sleep_side_effect

        mqtt_task._connect_loop()
        assert mock_sleep.called
