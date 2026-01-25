"""
Tests for serial port reading functionality.
"""
import pytest
import threading
import time
import datetime
from unittest.mock import MagicMock, patch, call
import s0pcm_reader
import state as state_module
import config as config_module
import importlib

@pytest.fixture(autouse=True)
def setup_serial_test_state():
    """Ensure a clean state for every test."""
    # Initialize basic config using standard logic
    config_module.read_config(state_module.config, "test")
    state_module.s0pcm_firmware = "Unknown"

class TestSerialPacketParsing:
    def test_handle_data_packet_updates_measurement(self, s0pcm_packets, mocker):
        mocker.patch.object(state_module, 'SetError')
        task = s0pcm_reader.TaskReadSerial(threading.Event(), threading.Event())
        
        data_str = s0pcm_packets['s0pcm2_data'].decode('ascii').rstrip('\r\n')
        task._handle_data_packet(data_str)
        
        assert 1 in state_module.measurement
        assert state_module.measurement[1]['total'] == 100
        
    def test_invalid_packet_sets_error(self, s0pcm_packets, mocker):
        mock_set_error = mocker.patch.object(state_module, 'SetError')
        task = s0pcm_reader.TaskReadSerial(threading.Event(), threading.Event())
        task._handle_data_packet("ID:8237:I:10:M1:0:100") # Too short
        assert mock_set_error.called

class TestPulseCountLogic:
    def test_pulse_increment(self):
        state_module.measurement.update({1: {'pulsecount': 100, 'total': 1000, 'today': 50}})
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 110)
        assert state_module.measurement[1]['total'] == 1010

    def test_pulse_reset_detection(self):
        state_module.measurement.update({1: {'pulsecount': 100, 'total': 1000, 'today': 50}})
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 10) # Restarted
        assert state_module.measurement[1]['total'] == 1010

    def test_update_meter_uninitialized(self):
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 5)
        assert 1 in state_module.measurement
        assert state_module.measurement[1]['total'] == 5

class TestSerialPacketAdvanced:
    def test_handle_header_parsing(self):
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._handle_header("/8237:S0 Pulse Counter V0.6")
        assert state_module.s0pcm_firmware == "S0 Pulse Counter V0.6"

    def test_read_loop_decoding_error(self, mocker):
        mock_ser = MagicMock()
        mock_ser.readline.side_effect = [b'\xff\xfe\xfd', b''] 
        mock_set_error = mocker.patch.object(state_module, 'SetError')
        task = s0pcm_reader.TaskReadSerial(None, threading.Event())
        task._read_loop(mock_ser)
        assert any("Failed to decode" in str(c) for c in mock_set_error.call_args_list)

class TestSerialConnection:
    def test_serial_connect_success(self, mock_serial):
        state_module.config['serial'].update({'port': '/dev/ttyACM0', 'baudrate': 9600, 'parity': 'E', 'stopbits': 1, 'bytesize': 7, 'timeout': None})
        task = s0pcm_reader.TaskReadSerial(None, threading.Event())
        mock_serial.return_value = MagicMock()
        assert task._connect() is not None

class TestDayChange:
    def test_day_change_resets_today(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        state_module.measurement.update({'date': yesterday, 1: {'pulsecount': 100, 'total': 1000, 'today': 50}})
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 110)
        assert state_module.measurement[1]['yesterday'] == 50
        assert state_module.measurement[1]['today'] == 10

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
