"""
Tests for serial port reading functionality.
"""
import pytest
import threading
import datetime
from unittest.mock import MagicMock, patch, call
import s0pcm_reader
import state as state_module
import config as config_module

@pytest.fixture(autouse=True)
def setup_serial_test_state():
    """Ensure a clean state for every test."""
    context = state_module.get_context()
    # Initialize basic config using standard logic
    context.config = config_module.read_config(version="test").model_dump()
    context.s0pcm_firmware = "Unknown"

class TestSerialPacketParsing:
    def test_handle_data_packet_updates_measurement(self, s0pcm_packets, mocker):
        task = s0pcm_reader.TaskReadSerial(threading.Event(), threading.Event())
        mocker.patch.object(task._context, 'set_error')
        
        data_str = s0pcm_packets['s0pcm2_data'].decode('ascii').rstrip('\r\n')
        task._handle_data_packet(data_str)
        
        context = state_module.get_context()
        assert 1 in context.state.meters
        assert context.state.meters[1].total == 100
        
    def test_invalid_packet_sets_error(self, s0pcm_packets, mocker):
        task = s0pcm_reader.TaskReadSerial(threading.Event(), threading.Event())
        mock_set_error = mocker.patch.object(task._context, 'set_error')
        task._handle_data_packet("ID:8237:I:10:M1:0:100") # Too short
        assert mock_set_error.called

class TestPulseCountLogic:
    def test_pulse_increment(self):
        # Initialize meter properly using state_module models
        context = state_module.get_context()
        context.state[1] = {'pulsecount': 100, 'total': 1000, 'today': 50}
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 110)
        assert context.state[1].total == 1010
        assert context.state[1].today == 60

    def test_pulse_reset_detection(self):
        context = state_module.get_context()
        context.state[1] = {'pulsecount': 100, 'total': 1000, 'today': 50}
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 10) # Restarted (pulsecount reset to 10)
        # Total should increase by 10
        assert context.state[1].total == 1010

    def test_update_meter_uninitialized(self):
        context = state_module.get_context()
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 5)
        assert 1 in context.state.meters
        assert context.state[1].total == 5

class TestSerialPacketAdvanced:
    def test_handle_header_parsing(self):
        context = state_module.get_context()
        task = s0pcm_reader.TaskReadSerial(None, None)
        
        # Verify context identity
        assert task._context is context
        assert task._context is state_module.get_context()
        
        task._handle_header("/8237:S0 Pulse Counter V0.6")
        assert context.s0pcm_firmware == "S0 Pulse Counter V0.6"

    def test_read_loop_decoding_error(self, mocker):
        mock_ser = MagicMock()
        mock_ser.readline.side_effect = [b'\xff\xfe\xfd', b''] 
        task = s0pcm_reader.TaskReadSerial(None, threading.Event())
        mock_set_error = mocker.patch.object(task._context, 'set_error')
        task._read_loop(mock_ser)
        assert any("Failed to decode" in str(c) for c in mock_set_error.call_args_list)

class TestSerialConnection:
    def test_serial_connect_success(self, mock_serial):
        # Setup config
        context = state_module.get_context()
        context.config['serial'] = {
            'port': '/dev/ttyACM0', 
            'baudrate': 9600, 
            'parity': 'E', 
            'stopbits': 1, 
            'bytesize': 7, 
            'timeout': None,
            'connect_retry': 5
        }
        task = s0pcm_reader.TaskReadSerial(None, threading.Event())
        mock_serial.return_value = MagicMock()
        assert task._connect() is not None

class TestDayChange:
    def test_day_change_resets_today(self):
        context = state_module.get_context()
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # Set date in state
        context.state.date = yesterday
        context.state[1] = {'pulsecount': 100, 'total': 1000, 'today': 50}
        
        task = s0pcm_reader.TaskReadSerial(None, None)
        task._update_meter(1, 110)
        
        assert context.state[1].yesterday == 50
        assert context.state[1].today == 10
        assert context.state.date == datetime.date.today()

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
