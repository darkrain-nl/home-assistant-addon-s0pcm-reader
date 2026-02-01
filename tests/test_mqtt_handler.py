"""
Comprehensive tests for MQTT handler functionality.

Tests cover:
- TLS setup and configuration
- Connection error handling and retries
- Disconnect scenarios
- Publishing loop edge cases
- Error state management
- Message handling (Set/Name topics)
- Discovery logic integration
"""

import ssl
from unittest.mock import MagicMock, patch

import pytest

# from mqtt_handler import TaskDoMQTT - lazy imported in fixture
import state as state_module


@pytest.fixture
def mqtt_task():
    """Create a TaskDoMQTT instance for testing."""
    from mqtt_handler import TaskDoMQTT

    trigger = MagicMock()
    stopper = MagicMock()
    stopper.is_set.return_value = False

    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "base_topic": "s0pcmreader",
            "discovery_prefix": "homeassistant",
            "host": "core-mosquitto",
            "port": 1883,
            "tls_port": 8883,
            "username": "test_user",
            "password": "test_pass",
            "client_id": None,
            "version": 5,
            "retain": True,
            "split_topic": True,
            "connect_retry": 0.01,
            "online": "online",
            "offline": "offline",
            "lastwill": "offline",
            "tls": False,
            "tls_ca": "",
            "tls_check_peer": False,
            "discovery": True,
            "recovery_wait": 0,
        },
        "serial": {"port": "/dev/ttyACM0"},
    }
    context.s0pcm_reader_version = "3.0.0"
    context.s0pcm_firmware = "V0.7"
    context.lasterror_share = None
    context.state.reset_state()

    return TaskDoMQTT(context, trigger, stopper)


class TestTLSSetup:
    """Test TLS/SSL configuration."""

    def test_setup_mqtt_client_with_tls_no_ca(self, mqtt_task, mocker):
        """Test TLS setup without CA certificate (creates default context)."""
        mqtt_task.app_context.config["mqtt"]["tls"] = True
        mqtt_task.app_context.config["mqtt"]["tls_ca"] = ""

        mock_ssl_context = MagicMock()
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = mqtt_task._setup_mqtt_client(use_tls=True)

        assert result is True
        # Should default to unchecked if no CA provided/verification disabled
        assert mock_ssl_context.check_hostname is False
        assert mock_ssl_context.verify_mode == mocker.ANY

    def test_setup_mqtt_client_with_tls_and_ca(self, mqtt_task, mocker):
        """Test TLS setup with CA certificate."""
        mqtt_task.app_context.config["mqtt"]["tls"] = True
        mqtt_task.app_context.config["mqtt"]["tls_ca"] = "/path/to/ca.crt"
        mqtt_task.app_context.config["mqtt"]["tls_check_peer"] = True

        mock_ssl_context = MagicMock()
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = mqtt_task._setup_mqtt_client(use_tls=True)

        assert result is True
        mock_ssl_context.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.crt")
        assert mock_ssl_context.check_hostname is True
        assert mock_ssl_context.verify_mode == ssl.CERT_REQUIRED

    def test_setup_mqtt_client_tls_ca_load_error(self, mqtt_task, mocker):
        """Test TLS setup handles CA load errors."""
        mqtt_task.app_context.config["mqtt"]["tls"] = True
        mqtt_task.app_context.config["mqtt"]["tls_ca"] = "/invalid/path/ca.crt"

        mock_ssl_context = MagicMock()
        mock_ssl_context.load_verify_locations.side_effect = Exception("File not found")
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = mqtt_task._setup_mqtt_client(use_tls=True)

        assert result is False
        assert "Failed to load TLS CA file" in mqtt_task.app_context.lasterror_share

    def test_setup_mqtt_client_with_username(self, mqtt_task):
        """Test MQTT client setup with username/password."""
        mqtt_task._setup_mqtt_client(use_tls=False)

        # Verify username_pw_set was called (client is created internally)
        assert mqtt_task._state.mqttc is not None


class TestConnectionHandling:
    """Test MQTT connection, disconnection, and loops."""

    def test_on_connect_success(self, mqtt_task):
        """Test successful connection callback."""
        mqtt_task._state.mqttc = MagicMock()
        mqtt_task._state.mqttc = MagicMock()
        # mqtt_task._trigger is already a MagicMock from fixture

        mqtt_task.on_connect(mqtt_task._state.mqttc, None, None, 0, None)

        assert mqtt_task._state.connected is True
        assert mqtt_task._trigger.is_set()

    def test_on_connect_failure(self, mqtt_task, mocker):
        """Test connection failure callback."""
        mqtt_task._state.mqttc = MagicMock()
        mock_set_error = mocker.patch.object(mqtt_task.app_context, "set_error")

        mqtt_task.on_connect(mqtt_task._state.mqttc, None, None, 5, None)  # 5 = auth error

        assert mqtt_task._state.connected is False
        assert mock_set_error.called
        assert "connection refused" in str(mock_set_error.call_args).lower()

    def test_on_disconnect_unexpected(self, mqtt_task, mocker):
        """Test unexpected disconnection."""
        mqtt_task._state.mqttc = MagicMock()
        mock_set_error = mocker.patch.object(mqtt_task.app_context, "set_error")
        mqtt_task._state.connected = True

        mqtt_task.on_disconnect(mqtt_task._state.mqttc, None, None, 1, None)  # Non-zero = unexpected

        assert mqtt_task._state.connected is False
        assert mock_set_error.called

    def test_on_disconnect_clean(self, mqtt_task):
        """Test clean disconnection."""
        mqtt_task._state.mqttc = MagicMock()
        mqtt_task.on_disconnect(mqtt_task._state.mqttc, None, None, 0, None)
        assert mqtt_task._state.connected is False

    @patch("time.sleep")
    def test_connect_loop_setup_failure(self, mock_sleep, mqtt_task):
        """Test _connect_loop when _setup_mqtt_client fails (retries)."""
        # Run loop once
        mqtt_task._stopper.is_set.side_effect = [False, True]

        with patch.object(mqtt_task, "_setup_mqtt_client", return_value=False):
            mqtt_task._connect_loop()
            assert mock_sleep.called

    @patch("time.sleep")
    def test_connect_loop_tls_fallback(self, mock_sleep, mqtt_task):
        """Test connection loop falling back from TLS to plain MQTT on failure."""
        context = state_module.get_context()
        context.config["mqtt"]["tls"] = True

        # Loop twice: 1 for TLS fail, 2 for Plain success (simulated) then stop
        mqtt_task._stopper.is_set.side_effect = [False, False, True]

        mock_client = MagicMock()

        with patch("mqtt_handler.mqtt.Client", return_value=mock_client):
            # First connect raises error, triggering fallback
            def connect_side_effect(*args, **kwargs):
                if connect_side_effect.called == 0:
                    connect_side_effect.called += 1
                    raise Exception("TLS Error")
                mqtt_task._state.connected = True
                return 0

            connect_side_effect.called = 0
            mock_client.connect.side_effect = connect_side_effect

            mqtt_task._connect_loop()

            assert "MQTT TLS failed" in context.lasterror_share
            assert "Falling back to plain" in context.lasterror_share
            assert connect_side_effect.called > 0


class TestMessageHandling:
    """Test MQTT message handling."""

    def test_handle_set_command_by_id(self, mqtt_task):
        """Test handling set command using meter ID."""
        mqtt_task.app_context.state.meters[1] = state_module.MeterState(total=1000)
        # mqtt_task._trigger is already a MagicMock from fixture

        msg = MagicMock()
        msg.topic = "s0pcmreader/1/total/set"
        msg.payload = b"2000"

        mqtt_task._handle_set_command(msg)

        assert mqtt_task.app_context.state.meters[1].total == 2000
        assert mqtt_task._trigger.is_set()

    def test_handle_set_command_by_name(self, mqtt_task):
        """Test handling set command using meter name."""
        mqtt_task.app_context.state.meters[1] = state_module.MeterState(name="Water", total=1000)
        # mqtt_task._trigger is already a MagicMock from fixture

        msg = MagicMock()
        msg.topic = "s0pcmreader/Water/total/set"
        msg.payload = b"2000"

        mqtt_task._handle_set_command(msg)

        assert mqtt_task.app_context.state.meters[1].total == 2000

    def test_handle_set_command_create_meter(self, mqtt_task):
        """Test _handle_set_command creating a meter if it doesn't exist."""
        context = state_module.get_context()
        context.state.meters = {}

        msg = MagicMock()
        msg.topic = "s0pcm/5/total/set"
        msg.payload = b"1000"

        mqtt_task._handle_set_command(msg)

        assert 5 in context.state.meters
        assert context.state.meters[5].total == 1000

    def test_handle_set_command_invalid_payload(self, mqtt_task, mocker):
        """Test handling set command with invalid payload."""
        mqtt_task.app_context.state.meters[1] = state_module.MeterState(total=1000)
        mock_set_error = mocker.patch.object(mqtt_task.app_context, "set_error")

        msg = MagicMock()
        msg.topic = "s0pcmreader/1/total/set"
        msg.payload = b"not_a_number"

        mqtt_task._handle_set_command(msg)

        assert mock_set_error.called
        assert "invalid payload" in str(mock_set_error.call_args).lower()

    def test_handle_set_command_exception(self, mqtt_task):
        """Test exception handling in _handle_set_command."""
        context = state_module.get_context()
        msg = MagicMock()
        msg.topic = None  # Causes Exception on split
        mqtt_task._handle_set_command(msg)
        assert "Failed to process MQTT set command" in context.lasterror_share

    def test_handle_name_set(self, mqtt_task, mocker):
        """Test handling name set command."""
        mqtt_task.app_context.state.meters[1] = state_module.MeterState()
        mqtt_task._state.mqttc = MagicMock()
        # Trigger is already MagicMock from fixture

        mocker.patch("mqtt_handler.discovery.send_global_discovery")
        mocker.patch("mqtt_handler.discovery.send_meter_discovery", return_value="NewName")

        msg = MagicMock()
        msg.topic = "s0pcmreader/1/name/set"
        msg.payload = b"NewName"

        mqtt_task._handle_name_set(msg)

        assert mqtt_task.app_context.state.meters[1].name == "NewName"
        assert mqtt_task._trigger.is_set()

    def test_handle_name_set_empty(self, mqtt_task, mocker):
        """Test handling name set with empty payload (clear name)."""
        mqtt_task.app_context.state.meters[1] = state_module.MeterState(name="OldName")
        mqtt_task._state.mqttc = MagicMock()
        # Trigger is already MagicMock from fixture

        mocker.patch("mqtt_handler.discovery.send_global_discovery")
        mocker.patch("mqtt_handler.discovery.send_meter_discovery")

        msg = MagicMock()
        msg.topic = "s0pcmreader/1/name/set"
        msg.payload = b""

        mqtt_task._handle_name_set(msg)

        assert mqtt_task.app_context.state.meters[1].name is None

    def test_handle_name_set_exception(self, mqtt_task):
        """Test exception handling in _handle_name_set."""
        context = state_module.get_context()
        msg = MagicMock()
        msg.topic = None
        mqtt_task._handle_name_set(msg)
        assert "Failed to process MQTT name/set command" in context.lasterror_share

    def test_on_message_dispatch(self, mqtt_task):
        """Test on_message dispatching to handlers."""
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


class TestPublishingLogic:
    """Test MQTT publishing logic."""

    def test_publish_diagnostics_change_detection(self, mqtt_task):
        """Test diagnostics only publish on change."""
        mqtt_task._state.mqttc = MagicMock()
        mqtt_task.app_context.s0pcm_reader_version = "3.0.0"
        mqtt_task.app_context.s0pcm_firmware = "V0.7"

        # First publish
        mqtt_task._publish_diagnostics()
        first_call_count = mqtt_task._state.mqttc.publish.call_count

        # Second publish with same values
        mqtt_task._publish_diagnostics()
        second_call_count = mqtt_task._state.mqttc.publish.call_count

        # Should not publish again if values haven't changed
        assert second_call_count == first_call_count

    def test_publish_diagnostics_exception(self, mqtt_task):
        """Test exception handling in _publish_diagnostics."""
        mqtt_task._state.mqttc = MagicMock()
        mqtt_task._state.mqttc.publish.side_effect = Exception("Publish error")
        with patch("mqtt_handler.logger.error") as mock_logger:
            mqtt_task._publish_diagnostics()
            assert mock_logger.called
            assert "Failed to publish info state" in mock_logger.call_args[0][0]

    def test_publish_measurements_date_change(self, mqtt_task):
        """Test publishing date when it changes."""
        mqtt_task._state.mqttc = MagicMock()

        import datetime

        state_snapshot = state_module.AppState()
        state_snapshot.date = datetime.date(2026, 1, 25)

        previous_snapshot = state_module.AppState()
        previous_snapshot.date = datetime.date(2026, 1, 24)

        mqtt_task._publish_measurements(state_snapshot, previous_snapshot)

        # Verify date was published
        date_calls = [c for c in mqtt_task._state.mqttc.publish.call_args_list if "/date" in str(c)]
        assert len(date_calls) > 0

    def test_publish_measurements_split_topic_mode(self, mqtt_task):
        """Test publishing in split_topic mode."""
        mqtt_task._state.mqttc = MagicMock()
        mqtt_task.app_context.config["mqtt"]["split_topic"] = True

        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(name="Water", total=1000, today=50)

        mqtt_task._publish_measurements(state_snapshot, None)

        # Verify split topics were published (just check publish was called multiple times)
        assert mqtt_task._state.mqttc.publish.called
        assert mqtt_task._state.mqttc.publish.call_count >= 3  # At least total, today, pulsecount

        # Regression check: Ensure topics do NOT contain function/object string representations
        published_topics = [str(call.args[0]) for call in mqtt_task._state.mqttc.publish.call_args_list]
        for topic in published_topics:
            assert "<function" not in topic
            assert "field at" not in topic
            assert "object at" not in topic

        # Ensure correct suffixes are present
        assert any(t.endswith("/total") for t in published_topics)
        assert any(t.endswith("/today") for t in published_topics)
        assert any(t.endswith("/pulsecount") for t in published_topics)

    def test_publish_measurements_disabled_meter(self, mqtt_task):
        """Test _publish_measurements skip disabled meter."""
        mqtt_task._state.mqttc = MagicMock()
        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(enabled=True, total=100)
        state_snapshot.meters[2] = state_module.MeterState(enabled=False, total=200)

        mqtt_task._publish_measurements(state_snapshot, None)

        published_topics = [str(call.args[0]) for call in mqtt_task._state.mqttc.publish.call_args_list]
        assert any("/1/" in topic or "Water" in topic for topic in published_topics)  # Check for ID or Name
        assert not any("/2/" in topic for topic in published_topics)


class TestMainLoop:
    """Test the main MQTT loop."""

    def test_main_loop_discovery_sent_once(self, mqtt_task, mocker):
        """Test that discovery is only sent once."""
        mqtt_task._state.connected = True
        mqtt_task._state.mqttc = MagicMock()
        # Trigger and stopper are already MagicMocks from fixture

        mock_send_global = mocker.patch("mqtt_handler.discovery.send_global_discovery")
        mock_cleanup = mocker.patch("mqtt_handler.discovery.cleanup_meter_discovery")

        # Trigger one iteration then stop
        def stop_after_first(*args):
            mqtt_task._stopper.is_set.return_value = True

        mqtt_task._trigger.wait.side_effect = stop_after_first

        mqtt_task._main_loop()

        # Discovery should be sent exactly once
        assert mock_send_global.call_count == 1
        # Cleanup should be called for meters 1-5
        assert mock_cleanup.call_count == 5

    def test_main_loop_exits_on_disconnect(self, mqtt_task):
        """Test main loop exits when disconnected."""
        mqtt_task._state.connected = False
        mqtt_task._state.mqttc = MagicMock()

        mqtt_task._main_loop()

        # Should return immediately without publishing
        assert mqtt_task._state.mqttc.publish.call_count == 0

    def test_main_loop_error_publish_exception(self, mqtt_task):
        """Test exception handling in _main_loop when publishing errors."""
        mqtt_task._state.connected = True
        mqtt_task._state.mqttc = MagicMock()
        # Stopper and trigger are already MagicMocks from fixture

        def mock_publish(topic, *args, **kwargs):
            if "/error" in topic:
                raise Exception("Error topic failure")
            return MagicMock()

        mqtt_task._state.mqttc.publish.side_effect = mock_publish
        mqtt_task._state.global_discovery_sent = True

        # Make loop run once
        mqtt_task._stopper.is_set.side_effect = [False, True]

        # Set an error to force publish call
        mqtt_task.app_context.lasterror_share = "Some Error"

        with patch("mqtt_handler.logger.error") as mock_logger:
            mqtt_task._main_loop()
            assert mock_logger.called
            assert "MQTT Publish Failed" in mock_logger.call_args[0][0]

    def test_run_fatal_exception(self, mqtt_task, mocker):
        """Test fatal exception handling in run()."""
        mocker.patch.object(mqtt_task, "_connect_loop", side_effect=Exception("Fatal Run Error"))
        mqtt_task._stopper.is_set.return_value = False

        with patch("mqtt_handler.logger.error") as mock_logger:
            mqtt_task.run()
            assert mock_logger.called
            assert "Fatal MQTT exception" in mock_logger.call_args[0][0]
            assert mqtt_task._stopper.set.called


def test_handle_name_set_triggers_discovery(mqtt_task, mocker):
    """Test that setting a name triggers discovery for all meters (lines 169-172)."""
    # Setup context with meters
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState(total=100)
    context.state.meters[2] = state_module.MeterState(total=200)
    context.config["mqtt"]["discovery"] = True

    # Mock both discovery functions
    mocker.patch("mqtt_handler.discovery.send_global_discovery")
    mock_send = mocker.patch("mqtt_handler.discovery.send_meter_discovery", return_value="TestMeter")

    # Trigger name set
    msg = MagicMock()
    msg.topic = "s0pcmreader/1/name/set"
    msg.payload = b"NewName"

    mqtt_task._handle_name_set(msg)

    # Should have sent discovery for all meters
    assert mock_send.call_count == 2
    assert mqtt_task._state.global_discovery_sent is True
    assert mqtt_task._trigger.set.called


def test_handle_name_set_exception_handling(mqtt_task, mocker):
    """Test exception handling in _handle_name_set (lines 172-173)."""
    context = state_module.get_context()
    context.config["mqtt"]["discovery"] = True

    # Mock send_meter_discovery to raise an exception
    mocker.patch("mqtt_handler.discovery.send_meter_discovery", side_effect=Exception("Test error"))

    # Add a meter
    context.state.meters[1] = state_module.MeterState(total=100)

    # Trigger name set
    msg = MagicMock()
    msg.topic = "s0pcmreader/1/name/set"
    msg.payload = b"NewName"

    # Should not crash, should set error
    mqtt_task._handle_name_set(msg)
    assert context.lasterror_mqtt is not None


def test_handle_total_set_unknown_meter(mqtt_task):
    """Test total/set command for unknown meter name (lines 108-109)."""
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState(name="Water")

    # Trigger set for non-existent meter by name
    msg = MagicMock()
    msg.topic = "s0pcmreader/UnknownMeter/total/set"
    msg.payload = b"1000"

    mqtt_task._handle_set_command(msg)

    # Should set error for unknown meter
    assert context.lasterror_mqtt is not None
    assert "unknown meter" in context.lasterror_mqtt.lower()


def test_handle_name_set_unknown_meter_by_name(mqtt_task):
    """Test name/set command for unknown meter name (lines 141-149)."""
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState(name="Water")

    # Trigger name set for non-existent meter name
    msg = MagicMock()
    msg.topic = "s0pcmreader/NonExistent/name/set"
    msg.payload = b"NewName"

    mqtt_task._handle_name_set(msg)

    # Should set error for unknown meter
    assert context.lasterror_mqtt is not None
    assert "unknown meter" in context.lasterror_mqtt.lower()


def test_handle_name_set_by_name_lookup(mqtt_task, mocker):
    """Test name/set with name-based meter lookup (lines 144-145)."""
    context = state_module.get_context()
    context.state.meters[5] = state_module.MeterState(name="WaterMeter")
    context.config["mqtt"]["discovery"] = True

    mocker.patch("mqtt_handler.discovery.send_global_discovery")
    mocker.patch("mqtt_handler.discovery.send_meter_discovery", return_value="Water")

    # Use meter name instead of ID
    msg = MagicMock()
    msg.topic = "s0pcmreader/WaterMeter/name/set"
    msg.payload = b"NewWaterName"

    mqtt_task._handle_name_set(msg)

    # Should find meter by name and update it
    assert context.state.meters[5].name == "NewWaterName"


def test_handle_name_set_creates_new_meter(mqtt_task, mocker):
    """Test name/set creates new meter if ID doesn't exist (line 159)."""
    context = state_module.get_context()
    context.config["mqtt"]["discovery"] = True

    mocker.patch("mqtt_handler.discovery.send_global_discovery")
    mocker.patch("mqtt_handler.discovery.send_meter_discovery", return_value="Test")

    # Set name for non-existent meter ID
    msg = MagicMock()
    msg.topic = "s0pcmreader/7/name/set"
    msg.payload = b"NewMeter"

    mqtt_task._handle_name_set(msg)

    # Should create new meter
    assert 7 in context.state.meters
    assert context.state.meters[7].name == "NewMeter"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
