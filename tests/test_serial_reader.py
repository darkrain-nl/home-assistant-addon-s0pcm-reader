"""
Tests for serial port reading functionality.
"""
import pytest
import threading
import time
import datetime
from unittest.mock import MagicMock, patch, call
import s0pcm_reader
import importlib

# Note: s0pcm_reader is stateful (module-level globals), so we need to reload it
# or patch it carefully in tests.

class TestSerialPacketParsing:
    """Test S0PCM packet parsing logic via TaskReadSerial."""
    
    def test_handle_data_packet_updates_measurement(self, s0pcm_packets, mocker):
        """Test that _handle_data_packet updates global measurements."""
        # Reset state by clearing and updating dicts in place
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({'serial': {'connect_retry': 5}})
        
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({'date': datetime.date.today()})
        
        # Patch SetError to verify it's called (or not) and avoid side effects
        mock_set_error = mocker.patch.object(s0pcm_reader, 'SetError')
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Parse data packet
        data_str = s0pcm_packets['s0pcm2_data'].decode('ascii').rstrip('\r\n')
        task._handle_data_packet(data_str)
        
        # Verify SetError called with None (success)
        mock_set_error.assert_called_with(None, category='serial')
        
        # Verify measurements were updated
        assert 1 in s0pcm_reader.measurement
        assert s0pcm_reader.measurement[1]['pulsecount'] == 100
        assert s0pcm_reader.measurement[1]['total'] == 100 # Initial update sets total
        
    def test_invalid_packet_sets_error(self, s0pcm_packets, mocker):
        """Test that invalid packets set the error state."""
        # Reset state
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({'serial': {'connect_retry': 5}})
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({'date': datetime.date.today()})
        
        # Patch SetError
        mock_set_error = mocker.patch.object(s0pcm_reader, 'SetError')
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Parse invalid packet (invalid length)
        data_str = "ID:8237:I:10:M1:0:100" 
        task._handle_data_packet(data_str)
        
        # Should call SetError with an error message
        assert mock_set_error.called
        call_args = mock_set_error.call_args
        assert call_args is not None
        assert "Invalid Packet" in call_args[0][0]
        assert call_args[1]['category'] == 'serial'

class TestSerialConnection:
    """Test serial port connection handling."""
    
    def test_serial_connect_success(self, mock_serial, mocker):
        """Test successful serial port connection."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'serial': {
                'port': '/dev/ttyACM0',
                'baudrate': 9600,
                'parity': 'E',
                'stopbits': 1,
                'bytesize': 7,
                'timeout': None,
                'connect_retry': 5
            }
        })
        
        # Patch SetError
        mocker.patch.object(s0pcm_reader, 'SetError')
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Mock successful connection
        mock_serial.return_value = MagicMock()
        
        # Connect should succeed
        ser = task._connect()
        assert ser is not None
    
    def test_serial_connect_retry(self, mock_serial, mocker):
        """Test serial port connection retry logic."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'serial': {
                'port': '/dev/ttyACM0',
                'baudrate': 9600,
                'parity': 'E',
                'stopbits': 1,
                'bytesize': 7,
                'timeout': None,
                'connect_retry': 0.01  # Fast retry for testing
            }
        })
        
        # Patch SetError
        mocker.patch.object(s0pcm_reader, 'SetError')
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Mock failed connection, then success (on the constructor)
        mock_serial.side_effect = [
            Exception("Connection failed"),
            Exception("Connection failed"),
            MagicMock()  # Success on third try
        ]
        
        # Should retry and eventually succeed
        ser = task._connect()
        assert ser is not None
        assert mock_serial.call_count == 3


class TestPulseCountLogic:
    """Test pulse counting and delta calculation state updates."""
    
    def test_pulse_increment(self):
        """Test normal pulse increment."""
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({
            'date': datetime.date.today(),
            1: {
                'pulsecount': 100,
                'total': 1000,
                'today': 50,
                'yesterday': 30
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Simulate pulse increment (110 - 100 = 10 delta)
        task._update_meter(1, 110)
        
        assert s0pcm_reader.measurement[1]['pulsecount'] == 110
        assert s0pcm_reader.measurement[1]['total'] == 1010
        assert s0pcm_reader.measurement[1]['today'] == 60
    
    def test_pulse_reset_detection(self):
        """Test detection of pulsecount reset (device restart)."""
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({
            'date': datetime.date.today(),
            1: {
                'pulsecount': 100,
                'total': 1000,
                'today': 50,
                'yesterday': 30
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Simulate pulsecount reset (restart, count is lower than previous)
        # Logic: treat new value as delta from 0
        task._update_meter(1, 10)
        
        assert s0pcm_reader.measurement[1]['pulsecount'] == 10
        assert s0pcm_reader.measurement[1]['total'] == 1010  # 1000 + 10
        assert s0pcm_reader.measurement[1]['today'] == 60  # 50 + 10


class TestDayChange:
    """Test day change detection and counter reset."""
    
    def test_day_change_resets_today(self):
        """Test that day change resets today counter."""
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({
            'date': yesterday,
            1: {
                'pulsecount': 100,
                'total': 1000,
                'today': 50,
                'yesterday': 30
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskReadSerial(trigger, stopper)
        
        # Simulate new pulse on new day
        task._update_meter(1, 110)
        
        # Today should be reset to just the delta
        # Yesterday should store the old today value
        assert s0pcm_reader.measurement[1]['yesterday'] == 50
        assert s0pcm_reader.measurement[1]['today'] == 10  # Only new pulses (110-100)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
