"""
Tests for serial handler module (serial_handler.py).
"""

import datetime
import threading
from unittest.mock import MagicMock, patch

import pytest

import config as config_module
from serial_handler import TaskReadSerial
import state as state_module


@pytest.fixture(autouse=True)
def setup_serial_test_state():
    """Ensure a clean state for every test."""
    context = state_module.get_context()
    # Initialize basic config using standard logic
    context.config = config_module.read_config(version="test").model_dump()
    context.s0pcm_firmware = "Unknown"
    context.state.reset_state()
    context.lasterror_serial = None


@pytest.fixture
def mock_serial():
    with patch("serial.serial_for_url") as mock:
        yield mock


@pytest.fixture
def s0pcm_packets():
    return {
        "s0pcm2_data": b"ID:8237:I:10:M1:0:100:M2:0:200\r\n",
        # Add more if needed
    }


class TestSerialPacketParsing:
    def test_handle_data_packet_updates_measurement(self, s0pcm_packets, mocker):
        context = state_module.get_context()
        task = TaskReadSerial(context, threading.Event(), threading.Event())
        mocker.patch.object(task.app_context, "set_error")

        data_str = s0pcm_packets["s0pcm2_data"].decode("ascii").rstrip("\r\n")
        task._handle_data_packet(data_str)

        context = state_module.get_context()
        assert 1 in context.state.meters
        assert context.state.meters[1].total == 100

    def test_invalid_packet_sets_error(self, s0pcm_packets, mocker):
        context = state_module.get_context()
        task = TaskReadSerial(context, threading.Event(), threading.Event())
        mock_set_error = mocker.patch.object(task.app_context, "set_error")
        task._handle_data_packet("ID:8237:I:10:M1:0:100")  # Too short
        assert mock_set_error.called


class TestPulseCountLogic:
    def test_pulse_increment(self):
        # Initialize meter properly using state_module models
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)
        task = TaskReadSerial(context, None, None)
        task._update_meter(1, 110)
        assert context.state.meters[1].total == 1010
        assert context.state.meters[1].today == 60

    def test_pulse_reset_detection(self):
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)
        task = TaskReadSerial(context, None, None)
        task._update_meter(1, 10)  # Restarted (pulsecount reset to 10)
        # Total should increase by 10
        assert context.state.meters[1].total == 1010

    def test_pulse_anomaly(self):
        """Test pulsecount anomaly (lower but not 0) (lines 162-165)."""
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000)
        task = TaskReadSerial(context, None, None)
        task._update_meter(1, 90)  # Lower than 100, not 0
        # Should record error
        assert context.lasterror_serial is not None
        assert "Pulsecount anomaly" in context.lasterror_serial
        # Should NOT increase total (delta is 90? No, delta is new pulsecount if < old?)
        # Logic: delta = pulsecount (line 167). Total += 90.
        assert context.state.meters[1].total == 1090

    def test_update_meter_uninitialized(self):
        context = state_module.AppContext()
        task = TaskReadSerial(context, None, None)
        task._update_meter(1, 5)
        assert 1 in context.state.meters
        assert context.state.meters[1].total == 5


class TestSerialPacketAdvanced:
    def test_handle_header_parsing(self):
        context = state_module.get_context()
        task = TaskReadSerial(context, None, None)

        # Verify context identity
        assert task.app_context is context
        assert task.app_context is state_module.get_context()

        task._handle_header("/8237:S0 Pulse Counter V0.6")
        assert context.s0pcm_firmware == "S0 Pulse Counter V0.6"

    def test_read_loop_decoding_error(self, mocker):
        mock_ser = MagicMock()
        mock_ser.readline.side_effect = [b"\xff\xfe\xfd", b""]
        context = state_module.get_context()
        task = TaskReadSerial(context, None, threading.Event())
        mock_set_error = mocker.patch.object(task.app_context, "set_error")
        task._read_loop(mock_ser)
        assert any("Failed to decode" in str(c) for c in mock_set_error.call_args_list)

    def test_read_loop_bounded_read(self):
        """Test that readline is called with a size limit (DoS prevention)."""
        mock_ser = MagicMock()
        mock_ser.readline.side_effect = [b""]  # Return empty to exit loop immediately (timeout path)
        context = state_module.get_context()
        task = TaskReadSerial(context, None, threading.Event())

        task._read_loop(mock_ser)

        # Verify readline was called with an integer argument (size limit)
        mock_ser.readline.assert_called_with(512)


class TestSerialConnection:
    def test_serial_connect_success(self, mock_serial):
        # Setup config
        context = state_module.get_context()
        context.config["serial"] = {
            "port": "/dev/ttyACM0",
            "baudrate": 9600,
            "parity": "E",
            "stopbits": 1,
            "bytesize": 7,
            "timeout": None,
            "connect_retry": 5,
        }
        task = TaskReadSerial(context, None, threading.Event())
        mock_serial.return_value = MagicMock()
        assert task._connect() is not None


class TestDayChange:
    def test_day_change_resets_today(self):
        context = state_module.get_context()
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # Set date in state
        context.state.date = yesterday
        context.state.meters[1] = state_module.MeterState(pulsecount=100, total=1000, today=50)

        task = TaskReadSerial(context, None, None)
        task._update_meter(1, 110)

        assert context.state.meters[1].yesterday == 50
        assert context.state.meters[1].today == 10
        assert context.state.date == datetime.date.today()


# --- From test_serial_missing.py ---


@pytest.fixture
def serial_task_missing():
    trigger = MagicMock()
    stopper = MagicMock()
    stopper.is_set.return_value = False

    context = state_module.get_context()
    context.config = {
        "serial": {
            "port": "/dev/ttyTEST",
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
            "timeout": 1,
            "connect_retry": 0.01,
        }
    }
    context.state.meters = {}
    context.lasterror_serial = None

    return TaskReadSerial(context, trigger, stopper)


def test_connect_exception_retry(serial_task_missing, mocker):
    """Test _connect exception handling and retry (lines 64-71)."""
    mock_serial = MagicMock()

    # First call raises Exception, second call returns mock_serial
    # This forces the loop to run once with an exception, covering lines 64-70
    with (
        patch("serial.serial_for_url", side_effect=[Exception("Connection Failed"), mock_serial]),
        patch("time.sleep") as mock_sleep,
    ):
        ser = serial_task_missing._connect()

        assert ser == mock_serial
        assert mock_sleep.called
        # Check that an error was logged/set
        assert serial_task_missing.app_context.lasterror_serial is not None
        assert "Connection Failed" in serial_task_missing.app_context.lasterror_serial


def test_handle_header_fallback(serial_task_missing):
    """Test _handle_header fallback paths (lines 86-88)."""
    # Test strict slicing fallback (line 84)
    serial_task_missing._handle_header("/SIMPLE")
    assert serial_task_missing.app_context.s0pcm_firmware == "SIMPLE"

    # Test exception fallback (line 86-87)
    class BadString:
        def __contains__(self, item):
            return True  # trigger first branch

        def split(self, *args, **kwargs):
            raise IndexError("Split failed")

        def __str__(self):
            return "BadString"

    bad_str = BadString()
    serial_task_missing._handle_header(bad_str)
    # Should fall back to assigning the object itself
    assert serial_task_missing.app_context.s0pcm_firmware == bad_str


def test_update_meter_reset_logging(serial_task_missing):
    """Test _update_meter reset logging (line 156)."""
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState(total=1000, pulsecount=500)

    # Pulsecount 0 triggers reset logic
    with patch("serial_handler.logger"):
        serial_task_missing._update_meter(1, 0)

        assert context.lasterror_serial is not None
        assert "S0PCM Reset detected" in context.lasterror_serial


def test_read_loop_errors(serial_task_missing):
    """Test _read_loop read error and junk packet (lines 182-184, 204)."""
    mock_serial = MagicMock()

    # 1. Read Error (causes break)
    mock_serial.readline.side_effect = Exception("Read IO Error")

    serial_task_missing._read_loop(mock_serial)
    assert "Serialport read error" in serial_task_missing.app_context.lasterror_serial

    # Reset for next part
    serial_task_missing.app_context.lasterror_serial = None
    serial_task_missing._stopper.is_set.side_effect = [False, True]  # Run once

    # 2. Junk Packet (lines 204)
    mock_serial.readline.side_effect = [b"JUNK_DATA\r\n"]

    serial_task_missing._read_loop(mock_serial)
    assert "Invalid Packet: 'JUNK_DATA'" in serial_task_missing.app_context.lasterror_serial


def test_run_fatal_exception(serial_task_missing, mocker):
    """Test run fatal exception (line 219-220)."""
    # Force exception at start of run
    serial_task_missing.app_context.recovery_event.wait = MagicMock(side_effect=Exception("Fatal Error"))

    with patch("serial_handler.logger.error") as mock_logger:
        serial_task_missing.run()

        assert mock_logger.called
        assert "Fatal exception in Serial Task" in mock_logger.call_args[0][0]
        assert serial_task_missing._stopper.set.called


def test_read_loop_header(serial_task_missing):
    """Test _read_loop header handling (lines 197-204)."""
    mock_serial = MagicMock()
    # 1. Header (hits 197-198)
    # 2. ID Packet (hits 199-200)
    # 3. Empty string decoded (hits 201-202)
    # 4. Empty bytes (hits 186 -> break)
    mock_serial.readline.side_effect = [b"/HEADER:V1\r\n", b"ID:123\r\n", b"\r\n", b""]

    with patch("serial_handler.logger") as mock_logger:
        serial_task_missing._read_loop(mock_serial)

        # Verify header parsed
        assert serial_task_missing.app_context.s0pcm_firmware == "V1"
        # Verify warning for empty packet
        assert mock_logger.warning.called
        assert "Empty Packet received" in mock_logger.warning.call_args[0][0]


def test_connect_stopper_set(serial_task_missing):
    """Test _connect returning None when stopper is set (line 71)."""
    # If stopper is set immediately, loop doesn't run, returns None
    serial_task_missing._stopper.is_set.return_value = True
    assert serial_task_missing._connect() is None

    # If stopper set after failure
    serial_task_missing._stopper.is_set.side_effect = [False, True]
    with patch("serial.serial_for_url", side_effect=Exception("Connection Failed")), patch("time.sleep"):
        assert serial_task_missing._connect() is None


# --- From test_loops.py ---


def test_task_read_serial_loop_execution(mocker):
    """Integrate TaskReadSerial loop."""
    context = state_module.get_context()
    context.config.update({"serial": {"connect_retry": 0.1}})

    stopper = threading.Event()
    task = TaskReadSerial(context, threading.Event(), stopper)

    # CRITICAL: Serial task waits for recovery event!
    context.recovery_event.set()

    mocker.patch.object(task, "_connect", return_value=MagicMock())

    def stop_logic(ser):
        stopper.set()

    mocker.patch.object(task, "_read_loop", side_effect=stop_logic)

    task.run()
    assert stopper.is_set()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
