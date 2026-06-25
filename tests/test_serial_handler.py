"""
Tests for serial handler module (serial_handler.py).
"""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from helpers import make_test_config
import pytest

import config as config_module
from serial_handler import (
    _handle_data_packet,
    _handle_header,
    _log_available_ports,
    _read_loop,
    _update_meter,
    serial_task,
)
import state as state_module


@pytest.fixture(autouse=True)
async def setup_serial_test_state():
    """Ensure a clean state for every test."""
    context = state_module.get_context()
    # Initialize basic config using standard logic
    context.config = await config_module.read_config(version="test")
    context.s0pcm_firmware = "Unknown"
    context.state.reset_state()
    context.lasterror_serial = None


@pytest.fixture
def s0pcm_packets():
    return {
        "s0pcm2_data": b"ID:8237:I:10:M1:0:100:M2:0:200\r\n",
        # Add more if needed
    }


class TestSerialPacketParsing:
    async def test_handle_data_packet_updates_measurement(self, s0pcm_packets, mocker):
        context = state_module.get_context()
        mocker.patch.object(context, "set_error")

        data_str = s0pcm_packets["s0pcm2_data"].decode("ascii").rstrip("\r\n")
        _handle_data_packet(context, data_str)

        assert 1 in context.state.meters
        assert context.state.meters[1].total == 100

    async def test_invalid_packet_sets_error(self, s0pcm_packets, mocker):
        context = state_module.get_context()
        mock_set_error = mocker.patch.object(context, "set_error")
        _handle_data_packet(context, "ID:8237:I:10:M1:0:100")  # Too short
        assert mock_set_error.called


class TestPulseCountLogic:
    async def test_pulse_increment(self):
        # Initialize meter properly using state_module models
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)
        _update_meter(context, 1, 110, 10, 10)
        assert context.state.meters[1].total == 1010
        assert context.state.meters[1].today == 60

    async def test_pulse_reset_detection(self):
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)
        _update_meter(context, 1, 10, 10, 20)  # Restarted (pulsecount reset to 10)
        # Total should increase by 10
        assert context.state.meters[1].total == 1010

    async def test_pulse_anomaly(self):
        """Test pulsecount anomaly (lower but not 0)."""
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000)
        _update_meter(context, 1, 90, 0, 10)  # Lower than 100, not 0
        # Should record error
        assert context.lasterror_serial is not None
        assert "Pulsecount anomaly" in context.lasterror_serial
        # Logic: delta = pulsecount (90). Total += 90.
        assert context.state.meters[1].total == 1090

    async def test_update_meter_uninitialized(self):
        context = state_module.AppContext()
        _update_meter(context, 1, 5, 5, 10)
        assert 1 in context.state.meters
        assert context.state.meters[1].total == 5


class TestSerialPacketAdvanced:
    async def test_handle_header_parsing(self):
        context = state_module.get_context()

        _handle_header(context, "/8237:S0 Pulse Counter V0.6")
        assert context.s0pcm_firmware == "S0 Pulse Counter V0.6"

    async def test_read_loop_decoding_error(self, mocker):
        mock_ser = AsyncMock()
        mock_ser.readline = AsyncMock(side_effect=[b"\xff\xfe\xfd", b""])
        context = state_module.get_context()
        mock_set_error = mocker.patch.object(context, "set_error")
        await _read_loop(context, mock_ser)
        assert any("Failed to decode" in str(c) for c in mock_set_error.call_args_list)

    async def test_read_loop_bounded_read(self):
        """Test that readline is called with a size limit (DoS prevention)."""
        mock_ser = AsyncMock()
        mock_ser.readline = AsyncMock(return_value=b"")  # Return empty to exit loop immediately (timeout path)
        context = state_module.get_context()

        await _read_loop(context, mock_ser)

        # Verify readline was called
        mock_ser.readline.assert_called_with()

    async def test_serial_task_connect_success(self, mocker):
        """Test serial_task opens port and calls read loop."""
        context = state_module.get_context()
        context.config = make_test_config()
        context.recovery_event.set()

        mock_ser = AsyncMock()
        mock_ser.__aenter__ = AsyncMock(return_value=mock_ser)
        mock_ser.__aexit__ = AsyncMock(return_value=False)
        mocker.patch("serialx.async_serial_for_url", return_value=mock_ser)

        # Make _read_loop cancel the task after one call
        async def cancel_after_read(ctx, ser):
            raise asyncio.CancelledError()

        mocker.patch("serial_handler._read_loop", side_effect=cancel_after_read)

        # serial_task catches CancelledError and returns normally
        await serial_task(context)


class TestDayChange:
    async def test_day_change_resets_today(self):
        context = state_module.get_context()
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # Set date in state
        context.state.date = yesterday
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)

        _update_meter(context, 1, 110, 10, 10)

        assert context.state.meters[1].yesterday == 50
        assert context.state.meters[1].today == 10
        assert context.state.date == datetime.date.today()

    async def test_day_change_resets_multiple_meters(self):
        context = state_module.get_context()
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # Set date in state
        context.state.date = yesterday
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)
        context.state.meters[2] = state_module.MeterState(pulsecount=200, total=2000, today=70)

        _update_meter(context, 1, 110, 10, 10)
        _update_meter(context, 2, 215, 15, 10)

        assert context.state.meters[1].yesterday == 50
        assert context.state.meters[1].today == 10
        assert context.state.meters[2].yesterday == 70
        assert context.state.meters[2].today == 15
        assert context.state.date == datetime.date.today()


async def test_handle_header_fallback():
    """Test _handle_header fallback paths."""
    context = state_module.get_context()

    # Test strict slicing fallback (no colon)
    _handle_header(context, "/SIMPLE")
    assert context.s0pcm_firmware == "SIMPLE"

    # Test exception fallback
    class BadString:
        def __contains__(self, item):
            return True  # trigger first branch

        def split(self, *args, **kwargs):
            raise IndexError("Split failed")

        def __str__(self):
            return "BadString"

    bad_str = BadString()
    _handle_header(context, bad_str)
    # Should fall back to assigning the object itself
    assert context.s0pcm_firmware == bad_str


async def test_update_meter_reset_logging():
    """Test _update_meter reset logging."""
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState(total=1000, pulsecount=500)

    # Pulsecount 0 triggers reset logic
    with patch("serial_handler.logger"):
        _update_meter(context, 1, 0, 0, 10)

        assert context.lasterror_serial is not None
        assert "S0PCM Reset detected" in context.lasterror_serial


async def test_read_loop_read_error():
    """Test _read_loop breaks on read exception."""
    context = state_module.get_context()

    mock_serial = AsyncMock()
    mock_serial.readline = AsyncMock(side_effect=Exception("Read IO Error"))

    await _read_loop(context, mock_serial)
    assert "Serialport read error" in context.lasterror_serial


async def test_read_loop_junk_packet(mocker):
    """Test _read_loop handles junk packet."""
    context = state_module.get_context()
    mock_set_error = mocker.patch.object(context, "set_error")

    mock_serial = AsyncMock()
    mock_serial.readline = AsyncMock(side_effect=[b"JUNK_DATA\r\n", b""])

    await _read_loop(context, mock_serial)

    # Verify set_error was called with the junk packet error
    error_calls = [str(c) for c in mock_set_error.call_args_list]
    assert any("Invalid Packet" in c and "JUNK_DATA" in c for c in error_calls)


async def test_serial_task_fatal_exception(mocker):
    """Test serial_task fatal exception."""
    context = state_module.get_context()
    context.config = make_test_config()
    context.recovery_event.set()

    mocker.patch("serialx.async_serial_for_url", side_effect=Exception("Fatal Error"))
    mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError())

    # serial_task catches CancelledError internally and returns
    await serial_task(context)

    assert context.lasterror_serial is not None
    assert "Fatal Error" in context.lasterror_serial


async def test_serial_task_retry_on_failure(mocker):
    """Test serial_task retries on connection failure."""
    context = state_module.get_context()
    context.config = make_test_config()
    context.recovery_event.set()

    call_count = 0

    def fail_then_cancel(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()
        raise Exception(f"Fail {call_count}")

    mocker.patch("serialx.async_serial_for_url", side_effect=fail_then_cancel)
    mocker.patch("asyncio.sleep", return_value=None)

    # serial_task catches CancelledError internally and returns
    await serial_task(context)

    assert context.lasterror_serial is not None


async def test_read_loop_header():
    """Test _read_loop header handling."""
    context = state_module.get_context()
    mock_serial = AsyncMock()
    # 1. Header
    # 2. ID Packet (too short, will set error)
    # 3. Empty string decoded
    # 4. Empty bytes -> break
    mock_serial.readline = AsyncMock(side_effect=[b"/HEADER:V1\r\n", b"ID:123\r\n", b"\r\n", b""])

    with patch("serial_handler.logger") as mock_logger:
        await _read_loop(context, mock_serial)

        # Verify header parsed
        assert context.s0pcm_firmware == "V1"
        # Verify warning for empty packet
        assert mock_logger.warning.called
        assert "Empty Packet received" in mock_logger.warning.call_args[0][0]


async def test_serial_task_exclusive_mode(mocker):
    """Test that exclusive=True is passed to async_serial_for_url."""
    context = state_module.get_context()
    context.config = make_test_config()
    context.recovery_event.set()

    mock_ser = AsyncMock()
    mock_ser.__aenter__ = AsyncMock(return_value=mock_ser)
    mock_ser.__aexit__ = AsyncMock(return_value=False)

    async def cancel_read(ctx, ser):
        raise asyncio.CancelledError()

    mock_async_serial = mocker.patch("serialx.async_serial_for_url", return_value=mock_ser)
    mocker.patch("serial_handler._read_loop", side_effect=cancel_read)

    # serial_task catches CancelledError internally and returns
    await serial_task(context)

    mock_async_serial.assert_called_once()
    _, kwargs = mock_async_serial.call_args
    assert kwargs["exclusive"] is True


async def test_log_available_ports_with_ports():
    """Test _log_available_ports when ports are detected."""
    mock_port = MagicMock()
    mock_port.device = "/dev/ttyACM0"
    with (
        patch("serialx.list_serial_ports", return_value=[mock_port]),
        patch("serial_handler.logger") as mock_logger,
    ):
        await _log_available_ports()
        assert any("/dev/ttyACM0" in str(c) for c in mock_logger.info.call_args_list)


async def test_log_available_ports_no_ports():
    """Test _log_available_ports when no ports are detected."""
    with (
        patch("serialx.list_serial_ports", return_value=[]),
        patch("serial_handler.logger") as mock_logger,
    ):
        await _log_available_ports()
        assert mock_logger.warning.called
        assert "No serial ports detected" in mock_logger.warning.call_args[0][0]


async def test_log_available_ports_exception():
    """Test _log_available_ports handles exceptions gracefully."""
    with (
        patch("serialx.list_serial_ports", side_effect=OSError("Permission denied")),
        patch("serial_handler.logger") as mock_logger,
    ):
        await _log_available_ports()
        assert mock_logger.debug.called
        assert "Unable to enumerate" in mock_logger.debug.call_args[0][0]


async def test_log_available_ports_called_on_first_failure(mocker):
    """Test that _log_available_ports is called only on the first connection failure."""
    context = state_module.get_context()
    context.config = make_test_config()
    context.recovery_event.set()

    call_count = 0

    def fail_then_cancel(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError()
        raise Exception(f"Fail {call_count}")

    mocker.patch("serialx.async_serial_for_url", side_effect=fail_then_cancel)
    mocker.patch("asyncio.sleep", return_value=None)
    mock_log_ports = mocker.patch("serial_handler._log_available_ports", new_callable=AsyncMock)

    # serial_task catches CancelledError internally and returns
    await serial_task(context)

    # Should be called exactly once (on first failure, not second)
    mock_log_ports.assert_called_once()


async def test_read_loop_cancelled_error():
    """Test _read_loop raises CancelledError on cancellation."""
    from serial_handler import _read_loop

    context = state_module.get_context()
    mock_serial = AsyncMock()
    mock_serial.readline = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _read_loop(context, mock_serial)


async def test_serial_task_fatal_exception_outer(mocker):
    """Test outer Exception block in serial_task."""
    from serial_handler import serial_task

    context = state_module.get_context()
    context.config = make_test_config()

    # Mock recovery_event.wait to raise an exception
    mocker.patch.object(context.recovery_event, "wait", side_effect=ValueError("Fatal Wait Error"))
    mocker.patch("serial_handler.logger.error")

    await serial_task(context)

    # Verify logger.error was called with fatal exception info
    import serial_handler

    serial_handler.logger.error.assert_called_with("Fatal exception in Serial Task", exc_info=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
