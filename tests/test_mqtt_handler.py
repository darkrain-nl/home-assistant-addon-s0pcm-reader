"""
Comprehensive tests for MQTT handler functionality.

Tests cover:
- TLS setup and configuration
- Publishing logic
- Error state management
- Message handling (Set/Name topics)
- Discovery logic integration
"""

import asyncio
import contextlib
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

from helpers import make_test_config
import pytest

import state as state_module


@pytest.fixture
def mqtt_context():
    """Create a test context for MQTT tests."""
    context = state_module.get_context()
    context.config = make_test_config()
    context.s0pcm_reader_version = "3.0.0"
    context.s0pcm_firmware = "V0.7"
    context.lasterror_share = None
    context.state.reset_state()
    return context


class TestTLSSetup:
    """Test TLS/SSL configuration."""

    def test_build_ssl_context_no_ca(self, mqtt_context, mocker):
        """Test TLS setup without CA certificate (creates default context)."""
        from mqtt_handler import _build_ssl_context

        mqtt_context.config = make_test_config(tls=True, tls_ca="")
        mock_ssl_context = MagicMock()
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = _build_ssl_context(mqtt_context)

        assert result is not None
        assert mock_ssl_context.check_hostname is False
        assert mock_ssl_context.verify_mode == mocker.ANY

    def test_build_ssl_context_with_ca(self, mqtt_context, mocker):
        """Test TLS setup with CA certificate."""
        from mqtt_handler import _build_ssl_context

        mqtt_context.config = make_test_config(tls=True, tls_ca="/path/to/ca.crt", tls_check_peer=True)
        mock_ssl_context = MagicMock()
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = _build_ssl_context(mqtt_context)

        assert result is not None
        mock_ssl_context.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.crt")
        assert mock_ssl_context.check_hostname is True
        assert mock_ssl_context.verify_mode == ssl.CERT_REQUIRED

    def test_build_ssl_context_ca_load_error(self, mqtt_context, mocker):
        """Test TLS setup handles CA load errors."""
        from mqtt_handler import _build_ssl_context

        mqtt_context.config = make_test_config(tls=True, tls_ca="/invalid/path/ca.crt")
        mock_ssl_context = MagicMock()
        mock_ssl_context.load_verify_locations.side_effect = Exception("File not found")
        mocker.patch("ssl.SSLContext", return_value=mock_ssl_context)

        result = _build_ssl_context(mqtt_context)

        assert result is None
        assert "Failed to load TLS CA file" in mqtt_context.lasterror_share


class TestMessageHandling:
    """Test MQTT message handling."""

    async def test_handle_set_command_by_id(self, mqtt_context):
        """Test handling set command using meter ID."""
        from mqtt_handler import _handle_set_command

        mqtt_context.state.meters[1] = state_module.MeterState(total=1000)

        await _handle_set_command(mqtt_context, "s0pcmreader/1/total/set", b"2000")

        assert mqtt_context.state.meters[1].total == 2000
        assert mqtt_context.trigger_event.is_set()

    async def test_handle_set_command_by_name(self, mqtt_context):
        """Test handling set command using meter name."""
        from mqtt_handler import _handle_set_command

        mqtt_context.state.meters[1] = state_module.MeterState(name="Water", total=1000)

        await _handle_set_command(mqtt_context, "s0pcmreader/Water/total/set", b"2000")

        assert mqtt_context.state.meters[1].total == 2000

    async def test_handle_set_command_create_meter(self, mqtt_context):
        """Test _handle_set_command creating a meter if it doesn't exist."""
        from mqtt_handler import _handle_set_command

        mqtt_context.state.meters = {}

        await _handle_set_command(mqtt_context, "s0pcmreader/5/total/set", b"1000")

        assert 5 in mqtt_context.state.meters
        assert mqtt_context.state.meters[5].total == 1000

    async def test_handle_set_command_invalid_payload(self, mqtt_context, mocker):
        """Test handling set command with invalid payload."""
        from mqtt_handler import _handle_set_command

        mqtt_context.state.meters[1] = state_module.MeterState(total=1000)
        mock_set_error = mocker.patch.object(mqtt_context, "set_error")

        await _handle_set_command(mqtt_context, "s0pcmreader/1/total/set", b"not_a_number")

        assert mock_set_error.called
        assert "invalid payload" in str(mock_set_error.call_args).lower()

    async def test_handle_set_command_exception(self, mqtt_context):
        """Test exception handling in _handle_set_command."""
        from mqtt_handler import _handle_set_command

        # None topic causes Exception on split
        with contextlib.suppress(Exception):
            await _handle_set_command(mqtt_context, None, b"1000")
        # With proper exception handling it should set error
        assert mqtt_context.lasterror_share is not None or mqtt_context.lasterror_mqtt is not None

    async def test_handle_name_set(self, mqtt_context, mocker):
        """Test handling name set command."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mqtt_context.state.meters[1] = state_module.MeterState()
        mock_client = AsyncMock()
        task_state = MqttTaskState()

        mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
        mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="NewName")

        await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"NewName")

        assert mqtt_context.state.meters[1].name == "NewName"
        assert mqtt_context.trigger_event.is_set()

    async def test_handle_name_set_empty(self, mqtt_context, mocker):
        """Test handling name set with empty payload (clear name)."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mqtt_context.state.meters[1] = state_module.MeterState(name="OldName")
        mock_client = AsyncMock()
        task_state = MqttTaskState()

        mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
        mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock)

        await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"")

        assert mqtt_context.state.meters[1].name is None

    async def test_handle_name_set_exception(self, mqtt_context):
        """Test exception handling in _handle_name_set."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mock_client = AsyncMock()
        task_state = MqttTaskState()

        await _handle_name_set(mqtt_context, mock_client, task_state, None, b"Name")
        assert mqtt_context.lasterror_mqtt is not None
        assert "Failed to process MQTT name/set command" in mqtt_context.lasterror_mqtt


class TestPublishingLogic:
    """Test MQTT publishing logic."""

    async def test_publish_diagnostics_change_detection(self, mqtt_context):
        """Test diagnostics only publish on change."""
        from mqtt_handler import MqttTaskState, _publish_diagnostics

        mock_client = AsyncMock()
        task_state = MqttTaskState()

        # First publish
        await _publish_diagnostics(mqtt_context, mock_client, task_state)
        assert mock_client.publish.call_count > 0

        # Second publish with same values
        mock_client.publish.reset_mock()
        await _publish_diagnostics(mqtt_context, mock_client, task_state)

        # Should not publish again if values haven't changed
        assert mock_client.publish.call_count == 0

    async def test_publish_diagnostics_exception(self, mqtt_context):
        """Test exception handling in _publish_diagnostics."""
        from mqtt_handler import MqttTaskState, _publish_diagnostics

        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(side_effect=Exception("Publish error"))
        task_state = MqttTaskState()

        with patch("mqtt_handler.logger.error") as mock_logger:
            await _publish_diagnostics(mqtt_context, mock_client, task_state)
            assert mock_logger.called
            assert "Failed to publish info state" in mock_logger.call_args[0][0]

    async def test_publish_measurements_date_change(self, mqtt_context):
        """Test publishing date when it changes."""
        import datetime

        from mqtt_handler import _publish_measurements

        mock_client = AsyncMock()

        state_snapshot = state_module.AppState()
        state_snapshot.date = datetime.date(2026, 1, 25)

        previous_snapshot = state_module.AppState()
        previous_snapshot.date = datetime.date(2026, 1, 24)

        await _publish_measurements(mqtt_context, mock_client, state_snapshot, previous_snapshot)

        # Verify date was published
        date_calls = [c for c in mock_client.publish.call_args_list if "/date" in str(c)]
        assert len(date_calls) > 0

    async def test_publish_measurements_split_topic_mode(self, mqtt_context):
        """Test publishing in split_topic mode."""
        from mqtt_handler import _publish_measurements

        mock_client = AsyncMock()
        mqtt_context.config = make_test_config(split_topic=True)

        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(name="Water", total=1000, today=50)

        await _publish_measurements(mqtt_context, mock_client, state_snapshot, None)

        # Verify split topics were published
        assert mock_client.publish.called
        assert mock_client.publish.call_count >= 3  # total, today, pulsecount

        # Regression check: Ensure topics do NOT contain function/object string representations
        published_topics = [str(call.args[0]) for call in mock_client.publish.call_args_list]
        for topic in published_topics:
            assert "<function" not in topic
            assert "field at" not in topic
            assert "object at" not in topic

        # Ensure correct suffixes are present
        assert any(t.endswith("/total") for t in published_topics)
        assert any(t.endswith("/today") for t in published_topics)

    async def test_publish_measurements_disabled_meter(self, mqtt_context):
        """Test _publish_measurements skip disabled meter."""
        from mqtt_handler import _publish_measurements

        mock_client = AsyncMock()
        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(enabled=True, total=100)
        state_snapshot.meters[2] = state_module.MeterState(enabled=False, total=200)

        await _publish_measurements(mqtt_context, mock_client, state_snapshot, None)

        published_topics = [str(call.args[0]) for call in mock_client.publish.call_args_list]
        assert any("/1/" in topic or "Water" in topic for topic in published_topics)
        assert not any("/2/" in topic for topic in published_topics)

    async def test_publish_measurements_combined_topic_mode(self, mqtt_context):
        """Test publishing when split_topic is False (JSON mode)."""
        from mqtt_handler import _publish_measurements

        mock_client = AsyncMock()
        mqtt_context.config = make_test_config(split_topic=False)

        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(name="Water", total=1000, today=50)

        await _publish_measurements(mqtt_context, mock_client, state_snapshot, None)

        # Verify JSON was published
        json_calls = [c for c in mock_client.publish.call_args_list if '"total": 1000' in str(c.args[1])]
        assert len(json_calls) > 0
        payload = json_calls[0].args[1]
        assert '"today": 50' in payload


async def test_handle_name_set_triggers_discovery(mqtt_context, mocker):
    """Test that setting a name triggers discovery for all meters."""
    from mqtt_handler import MqttTaskState, _handle_name_set

    mqtt_context.state.meters[1] = state_module.MeterState(total=100)
    mqtt_context.state.meters[2] = state_module.MeterState(total=200)
    mqtt_context.config = make_test_config(discovery=True)

    mock_client = AsyncMock()
    task_state = MqttTaskState()

    mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
    mock_send = mocker.patch(
        "mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="TestMeter"
    )

    await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"NewName")

    # Should have sent discovery for all meters
    assert mock_send.call_count == 2
    assert task_state.global_discovery_sent is True
    assert mqtt_context.trigger_event.is_set()


async def test_handle_name_set_exception_handling(mqtt_context, mocker):
    """Test exception handling in _handle_name_set."""
    from mqtt_handler import MqttTaskState, _handle_name_set

    mqtt_context.config = make_test_config(discovery=True)
    mock_client = AsyncMock()
    task_state = MqttTaskState()

    # Mock send_meter_discovery to raise an exception
    mocker.patch(
        "mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, side_effect=Exception("Test error")
    )

    # Add a meter
    mqtt_context.state.meters[1] = state_module.MeterState(total=100)

    await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"NewName")
    assert mqtt_context.lasterror_mqtt is not None


async def test_handle_total_set_unknown_meter(mqtt_context):
    """Test total/set command for unknown meter name."""
    from mqtt_handler import _handle_set_command

    mqtt_context.state.meters[1] = state_module.MeterState(name="Water")

    await _handle_set_command(mqtt_context, "s0pcmreader/UnknownMeter/total/set", b"1000")

    assert mqtt_context.lasterror_mqtt is not None
    assert "unknown meter" in mqtt_context.lasterror_mqtt.lower()


async def test_handle_name_set_unknown_meter_by_name(mqtt_context):
    """Test name/set command for unknown meter name."""
    from mqtt_handler import MqttTaskState, _handle_name_set

    mqtt_context.state.meters[1] = state_module.MeterState(name="Water")
    mock_client = AsyncMock()
    task_state = MqttTaskState()

    await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/NonExistent/name/set", b"NewName")

    assert mqtt_context.lasterror_mqtt is not None
    assert "unknown meter" in mqtt_context.lasterror_mqtt.lower()


async def test_handle_name_set_by_name_lookup(mqtt_context, mocker):
    """Test name/set with name-based meter lookup."""
    from mqtt_handler import MqttTaskState, _handle_name_set

    mqtt_context.state.meters[5] = state_module.MeterState(name="WaterMeter")
    mqtt_context.config = make_test_config(discovery=True)
    mock_client = AsyncMock()
    task_state = MqttTaskState()

    mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
    mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="Water")

    await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/WaterMeter/name/set", b"NewWaterName")

    assert mqtt_context.state.meters[5].name == "NewWaterName"


async def test_handle_name_set_creates_new_meter(mqtt_context, mocker):
    """Test name/set creates new meter if ID doesn't exist."""
    from mqtt_handler import MqttTaskState, _handle_name_set

    mqtt_context.config = make_test_config(discovery=True)
    mock_client = AsyncMock()
    task_state = MqttTaskState()

    mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
    mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="Test")

    await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/7/name/set", b"NewMeter")

    assert 7 in mqtt_context.state.meters
    assert mqtt_context.state.meters[7].name == "NewMeter"


class TestSecurityHardening:
    """Tests for security hardening measures."""

    async def test_name_set_sanitizes_mqtt_characters(self, mqtt_context, mocker):
        """Test that /+# characters are stripped from meter names."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mqtt_context.state.meters[1] = state_module.MeterState()
        mock_client = AsyncMock()
        task_state = MqttTaskState()

        mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
        mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="MyMeter")

        await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"My/Meter+Name#Test")

        assert mqtt_context.state.meters[1].name == "MyMeterNameTest"

    async def test_name_set_only_special_chars_becomes_none(self, mqtt_context, mocker):
        """Test that a name consisting only of MQTT special chars becomes None."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mqtt_context.state.meters[1] = state_module.MeterState(name="OldName")
        mock_client = AsyncMock()
        task_state = MqttTaskState()

        mocker.patch("mqtt_handler.discovery.send_global_discovery", new_callable=AsyncMock)
        mocker.patch("mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock)

        await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"/+#")

        assert mqtt_context.state.meters[1].name is None

    async def test_handle_set_command_oversized_payload(self, mqtt_context, mocker):
        """Test that oversized payloads on total/set are rejected."""
        from mqtt_handler import _handle_set_command

        mqtt_context.state.meters[1] = state_module.MeterState(total=1000)
        mock_set_error = mocker.patch.object(mqtt_context, "set_error")

        await _handle_set_command(mqtt_context, "s0pcmreader/1/total/set", b"x" * 257)

        assert mock_set_error.called
        assert "oversized payload" in str(mock_set_error.call_args).lower()
        # Total should NOT have changed
        assert mqtt_context.state.meters[1].total == 1000

    async def test_handle_name_set_oversized_payload(self, mqtt_context, mocker):
        """Test that oversized payloads on name/set are rejected."""
        from mqtt_handler import MqttTaskState, _handle_name_set

        mqtt_context.state.meters[1] = state_module.MeterState(name="Water")
        mock_client = AsyncMock()
        task_state = MqttTaskState()
        mock_set_error = mocker.patch.object(mqtt_context, "set_error")

        await _handle_name_set(mqtt_context, mock_client, task_state, "s0pcmreader/1/name/set", b"A" * 257)

        assert mock_set_error.called
        assert "oversized payload" in str(mock_set_error.call_args).lower()
        # Name should NOT have changed
        assert mqtt_context.state.meters[1].name == "Water"


class TestMQTTAdditionalCoverage:
    """Additional tests to reach near-100% coverage."""

    async def test_publish_loop_discovery(self, mqtt_context, mocker):
        """Test that _publish_loop sends discovery for new meters."""
        from mqtt_handler import MqttTaskState, _publish_loop

        mock_client = AsyncMock()
        task_state = MqttTaskState()
        task_state.global_discovery_sent = True  # Skip global discovery

        # Add a meter
        mqtt_context.state.meters[1] = state_module.MeterState(name="TestMeter")

        mock_send = mocker.patch(
            "mqtt_handler.discovery.send_meter_discovery", new_callable=AsyncMock, return_value="TestMeter"
        )

        # Make trigger event fire once then cancel
        call_count = 0

        async def trigger_once():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()

        mqtt_context.trigger_event.wait = trigger_once
        mqtt_context.trigger_event.set()

        with pytest.raises(asyncio.CancelledError):
            await _publish_loop(mqtt_context, mock_client, task_state)

        assert mock_send.call_count == 1
        assert task_state.discovered_meters[1] == "TestMeter"

    def test_resolve_meter_id_by_name(self, mqtt_context):
        """Test resolving meter ID by name."""
        from mqtt_handler import _resolve_meter_id

        mqtt_context.state.meters[1] = state_module.MeterState(name="Water")

        assert _resolve_meter_id(mqtt_context, "Water") == 1
        assert _resolve_meter_id(mqtt_context, "water") == 1  # Case-insensitive
        assert _resolve_meter_id(mqtt_context, "NonExistent") is None
        assert _resolve_meter_id(mqtt_context, "1") == 1  # Numeric ID


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
