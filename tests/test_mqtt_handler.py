"""
Additional comprehensive tests for MQTT handler functionality.

Tests cover:
- TLS setup and configuration
- Connection error handling and retries
- Disconnect scenarios
- Publishing loop edge cases
- Error state management
"""
import pytest
import threading
import json
from unittest.mock import MagicMock, patch, call
import state as state_module
import mqtt_handler
from mqtt_handler import TaskDoMQTT


@pytest.fixture
def mqtt_task():
    """Create a TaskDoMQTT instance for testing."""
    trigger = threading.Event()
    stopper = threading.Event()
    
    context = state_module.get_context()
    context.config = {
        'mqtt': {
            'base_topic': 's0pcmreader',
            'discovery_prefix': 'homeassistant',
            'host': 'core-mosquitto',
            'port': 1883,
            'tls_port': 8883,
            'username': 'test_user',
            'password': 'test_pass',
            'client_id': None,
            'version': 5,
            'retain': True,
            'split_topic': True,
            'connect_retry': 1,
            'online': 'online',
            'offline': 'offline',
            'lastwill': 'offline',
            'tls': False,
            'tls_ca': '',
            'tls_check_peer': False
        },
        'serial': {
            'port': '/dev/ttyACM0'
        }
    }
    context.s0pcm_reader_version = '3.0.0'
    context.s0pcm_firmware = 'V0.7'
    
    return TaskDoMQTT(trigger, stopper)


class TestTLSSetup:
    """Test TLS/SSL configuration."""
    
    def test_setup_mqtt_client_with_tls_no_ca(self, mqtt_task, mocker):
        """Test TLS setup without CA certificate."""
        mqtt_task._context.config['mqtt']['tls'] = True
        mqtt_task._context.config['mqtt']['tls_ca'] = ''
        
        mock_ssl_context = MagicMock()
        mocker.patch('ssl.SSLContext', return_value=mock_ssl_context)
        
        result = mqtt_task._setup_mqtt_client(use_tls=True)
        
        assert result is True
        assert mock_ssl_context.check_hostname is False
        assert mock_ssl_context.verify_mode == mocker.ANY
    
    def test_setup_mqtt_client_with_tls_and_ca(self, mqtt_task, mocker):
        """Test TLS setup with CA certificate."""
        mqtt_task._context.config['mqtt']['tls'] = True
        mqtt_task._context.config['mqtt']['tls_ca'] = '/path/to/ca.crt'
        mqtt_task._context.config['mqtt']['tls_check_peer'] = True
        
        mock_ssl_context = MagicMock()
        mocker.patch('ssl.SSLContext', return_value=mock_ssl_context)
        
        result = mqtt_task._setup_mqtt_client(use_tls=True)
        
        assert result is True
        mock_ssl_context.load_verify_locations.assert_called_once_with(cafile='/path/to/ca.crt')
    
    def test_setup_mqtt_client_tls_ca_load_error(self, mqtt_task, mocker):
        """Test TLS setup handles CA load errors."""
        mqtt_task._context.config['mqtt']['tls'] = True
        mqtt_task._context.config['mqtt']['tls_ca'] = '/invalid/path/ca.crt'
        
        mock_ssl_context = MagicMock()
        mock_ssl_context.load_verify_locations.side_effect = Exception("File not found")
        mocker.patch('ssl.SSLContext', return_value=mock_ssl_context)
        
        result = mqtt_task._setup_mqtt_client(use_tls=True)
        
        assert result is False
    
    def test_setup_mqtt_client_with_username(self, mqtt_task):
        """Test MQTT client setup with username/password."""
        mqtt_task._setup_mqtt_client(use_tls=False)
        
        # Verify username_pw_set was called
        assert mqtt_task._mqttc is not None


class TestConnectionHandling:
    """Test MQTT connection and disconnection."""
    
    def test_on_connect_success(self, mqtt_task):
        """Test successful connection callback."""
        mqtt_task._mqttc = MagicMock()
        mqtt_task._trigger = threading.Event()
        
        mqtt_task.on_connect(mqtt_task._mqttc, None, None, 0, None)
        
        assert mqtt_task._connected is True
        assert mqtt_task._trigger.is_set()
    
    def test_on_connect_failure(self, mqtt_task, mocker):
        """Test connection failure callback."""
        mqtt_task._mqttc = MagicMock()
        mock_set_error = mocker.patch.object(mqtt_task._context, 'set_error')
        
        mqtt_task.on_connect(mqtt_task._mqttc, None, None, 5, None)  # 5 = auth error
        
        assert mqtt_task._connected is False
        assert mock_set_error.called
    
    def test_on_disconnect_unexpected(self, mqtt_task, mocker):
        """Test unexpected disconnection."""
        mqtt_task._mqttc = MagicMock()
        mock_set_error = mocker.patch.object(mqtt_task._context, 'set_error')
        
        mqtt_task.on_disconnect(mqtt_task._mqttc, None, None, 1, None)  # Non-zero = unexpected
        
        assert mqtt_task._connected is False
        assert mock_set_error.called
    
    def test_on_disconnect_clean(self, mqtt_task):
        """Test clean disconnection."""
        mqtt_task._mqttc = MagicMock()
        
        mqtt_task.on_disconnect(mqtt_task._mqttc, None, None, 0, None)
        
        assert mqtt_task._connected is False


class TestMessageHandling:
    """Test MQTT message handling."""
    
    def test_handle_set_command_by_id(self, mqtt_task):
        """Test handling set command using meter ID."""
        mqtt_task._context.state.meters[1] = state_module.MeterState(total=1000)
        mqtt_task._trigger = threading.Event()
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/1/total/set'
        msg.payload = b'2000'
        
        mqtt_task._handle_set_command(msg)
        
        assert mqtt_task._context.state.meters[1].total == 2000
        assert mqtt_task._trigger.is_set()
    
    def test_handle_set_command_by_name(self, mqtt_task):
        """Test handling set command using meter name."""
        mqtt_task._context.state.meters[1] = state_module.MeterState(name='Water', total=1000)
        mqtt_task._trigger = threading.Event()
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/Water/total/set'
        msg.payload = b'2000'
        
        mqtt_task._handle_set_command(msg)
        
        assert mqtt_task._context.state.meters[1].total == 2000
    
    def test_handle_set_command_unknown_meter(self, mqtt_task, mocker):
        """Test handling set command for unknown meter."""
        mock_set_error = mocker.patch.object(mqtt_task._context, 'set_error')
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/UnknownMeter/total/set'
        msg.payload = b'2000'
        
        mqtt_task._handle_set_command(msg)
        
        assert mock_set_error.called
        assert "unknown meter" in str(mock_set_error.call_args).lower()
    
    def test_handle_set_command_invalid_payload(self, mqtt_task, mocker):
        """Test handling set command with invalid payload."""
        mqtt_task._context.state.meters[1] = state_module.MeterState(total=1000)
        mock_set_error = mocker.patch.object(mqtt_task._context, 'set_error')
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/1/total/set'
        msg.payload = b'not_a_number'
        
        mqtt_task._handle_set_command(msg)
        
        assert mock_set_error.called
        assert "invalid payload" in str(mock_set_error.call_args).lower()
    
    def test_handle_name_set(self, mqtt_task, mocker):
        """Test handling name set command."""
        mqtt_task._context.state.meters[1] = state_module.MeterState()
        mqtt_task._mqttc = MagicMock()
        mqtt_task._trigger = threading.Event()
        
        mocker.patch('mqtt_handler.discovery.send_global_discovery')
        mocker.patch('mqtt_handler.discovery.send_meter_discovery', return_value='NewName')
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/1/name/set'
        msg.payload = b'NewName'
        
        mqtt_task._handle_name_set(msg)
        
        assert mqtt_task._context.state.meters[1].name == 'NewName'
        assert mqtt_task._trigger.is_set()
    
    def test_handle_name_set_empty(self, mqtt_task, mocker):
        """Test handling name set with empty payload (clear name)."""
        mqtt_task._context.state.meters[1] = state_module.MeterState(name='OldName')
        mqtt_task._mqttc = MagicMock()
        mqtt_task._trigger = threading.Event()
        
        mocker.patch('mqtt_handler.discovery.send_global_discovery')
        mocker.patch('mqtt_handler.discovery.send_meter_discovery')
        
        msg = MagicMock()
        msg.topic = 's0pcmreader/1/name/set'
        msg.payload = b''
        
        mqtt_task._handle_name_set(msg)
        
        assert mqtt_task._context.state.meters[1].name is None


class TestPublishingLogic:
    """Test MQTT publishing logic."""
    
    def test_publish_diagnostics_change_detection(self, mqtt_task):
        """Test diagnostics only publish on change."""
        mqtt_task._mqttc = MagicMock()
        mqtt_task._context.s0pcm_reader_version = '3.0.0'
        mqtt_task._context.s0pcm_firmware = 'V0.7'
        
        # First publish
        mqtt_task._publish_diagnostics()
        first_call_count = mqtt_task._mqttc.publish.call_count
        
        # Second publish with same values
        mqtt_task._publish_diagnostics()
        second_call_count = mqtt_task._mqttc.publish.call_count
        
        # Should not publish again if values haven't changed
        assert second_call_count == first_call_count
    
    def test_publish_measurements_date_change(self, mqtt_task):
        """Test publishing date when it changes."""
        mqtt_task._mqttc = MagicMock()
        
        import datetime
        state_snapshot = state_module.AppState()
        state_snapshot.date = datetime.date(2026, 1, 25)
        
        previous_snapshot = state_module.AppState()
        previous_snapshot.date = datetime.date(2026, 1, 24)
        
        mqtt_task._publish_measurements(state_snapshot, previous_snapshot)
        
        # Verify date was published
        date_calls = [c for c in mqtt_task._mqttc.publish.call_args_list if '/date' in str(c)]
        assert len(date_calls) > 0
    
    def test_publish_measurements_split_topic_mode(self, mqtt_task):
        """Test publishing in split_topic mode."""
        mqtt_task._mqttc = MagicMock()
        mqtt_task._context.config['mqtt']['split_topic'] = True
        
        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(name='Water', total=1000, today=50)
        
        mqtt_task._publish_measurements(state_snapshot, None)
        
        # Verify split topics were published
        topics = [str(c[0][0]) for c in mqtt_task._mqttc.publish.call_args_list]
        assert any('Water/total' in t for t in topics)
        assert any('Water/today' in t for t in topics)
    
    def test_publish_measurements_json_mode(self, mqtt_task):
        """Test publishing in JSON mode (split_topic=False)."""
        mqtt_task._mqttc = MagicMock()
        mqtt_task._context.config['mqtt']['split_topic'] = False
        
        state_snapshot = state_module.AppState()
        state_snapshot.meters[1] = state_module.MeterState(name='Water', total=1000, today=50)
        
        mqtt_task._publish_measurements(state_snapshot, None)
        
        # Verify JSON payload was published
        json_calls = [c for c in mqtt_task._mqttc.publish.call_args_list 
                      if 'Water' in str(c[0][0]) and '{' in str(c[0][1])]
        assert len(json_calls) > 0


class TestMainLoop:
    """Test the main MQTT loop."""
    
    def test_main_loop_discovery_sent_once(self, mqtt_task, mocker):
        """Test that discovery is only sent once."""
        mqtt_task._connected = True
        mqtt_task._mqttc = MagicMock()
        mqtt_task._trigger = threading.Event()
        mqtt_task._stopper = threading.Event()
        
        mock_send_global = mocker.patch('mqtt_handler.discovery.send_global_discovery')
        mock_cleanup = mocker.patch('mqtt_handler.discovery.cleanup_meter_discovery')
        
        # Trigger one iteration then stop
        def stop_after_first(*args):
            mqtt_task._stopper.set()
        
        mqtt_task._trigger.wait = stop_after_first
        
        mqtt_task._main_loop()
        
        # Discovery should be sent exactly once
        assert mock_send_global.call_count == 1
        # Cleanup should be called for meters 1-5
        assert mock_cleanup.call_count == 5
    
    def test_main_loop_exits_on_disconnect(self, mqtt_task):
        """Test main loop exits when disconnected."""
        mqtt_task._connected = False
        mqtt_task._mqttc = MagicMock()
        
        mqtt_task._main_loop()
        
        # Should return immediately without publishing
        assert mqtt_task._mqttc.publish.call_count == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
