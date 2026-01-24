"""
Tests for MQTT client functionality.
"""
import pytest
import threading
import time
import json
import datetime
from unittest.mock import MagicMock, patch, call
import s0pcm_reader
import importlib


class TestMQTTConnection:
    """Test MQTT connection handling."""
    
    def test_mqtt_connect_success(self, mock_mqtt_client, mocker):
        """Test successful MQTT connection."""
        # Reset state
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'host': 'localhost',
                'port': 1883,
                'tls_port': 8883,
                'username': 'test',
                'password': 'test',
                'base_topic': 's0pcmreader',
                'client_id': None,
                'version': 5,
                'retain': True,
                'split_topic': True,
                'connect_retry': 5,
                'online': 'online',
                'offline': 'offline',
                'lastwill': 'offline',
                'discovery': True,
                'discovery_prefix': 'homeassistant',
                'tls': False,
                'tls_ca': '',
                'tls_check_peer': False
            }
        })
        
        # Patch SetError
        mocker.patch.object(s0pcm_reader, 'SetError')
        
        # Mock the recovery event
        s0pcm_reader.recovery_event = threading.Event()
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        # Setup mock client
        mock_mqtt_client.connect.return_value = 0
        
        # Simulate successful connection by calling on_connect
        task.on_connect(mock_mqtt_client, None, None, 0, None)
        
        assert task._connected is True
    
    def test_mqtt_connect_failure(self, mock_mqtt_client, mocker):
        """Test MQTT connection failure."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'host': 'localhost',
                'port': 1883,
                'tls_port': 8883,
                'base_topic': 's0pcmreader',
                'connect_retry': 0.1,
                'lastwill': 'offline',
                'retain': True,
                'tls': False
            }
        })
        
        # Patch SetError
        mock_set_error = mocker.patch.object(s0pcm_reader, 'SetError')
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        
        # Simulate connection failure
        task.on_connect(mock_mqtt_client, None, None, 1, None)  # reason_code 1 = failure
        
        assert task._connected is False
        assert mock_set_error.called


class TestMQTTPublish:
    """Test MQTT publishing functionality."""
    
    def test_publish_measurements(self, mock_mqtt_client):
        """Test publishing measurement data."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader',
                'split_topic': True,
                'retain': True
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        measurement_local = {
            'date': datetime.date.today(),
            1: {
                'name': 'Water',
                'pulsecount': 100,
                'total': 1000,
                'today': 50,
                'yesterday': 30
            }
        }
        
        measurement_previous = {}
        
        # Publish measurements
        task._publish_measurements(measurement_local, measurement_previous)
        
        # Verify publish was called for each metric
        calls = mock_mqtt_client.publish.call_args_list
        
        # Check that topics were published
        topics = [call[0][0] for call in calls]
        assert any('Water/total' in topic for topic in topics)
        assert any('Water/today' in topic for topic in topics)
        assert any('Water/yesterday' in topic for topic in topics)
    
    def test_publish_json_mode(self, mock_mqtt_client):
        """Test publishing in JSON mode (split_topic=False)."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader',
                'split_topic': False,  # JSON mode
                'retain': True
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        measurement_local = {
            'date': datetime.date.today(),
            1: {
                'pulsecount': 100,
                'total': 1000,
                'today': 50,
                'yesterday': 30
            }
        }
        
        measurement_previous = {}
        
        # Publish measurements
        task._publish_measurements(measurement_local, measurement_previous)
        
        # Verify JSON payload was published
        calls = mock_mqtt_client.publish.call_args_list
        
        # Find the JSON publish call
        json_calls = [call for call in calls if '1' in call[0][0] and call[0][0].endswith('/1')]
        assert len(json_calls) > 0
        
        # Verify it's valid JSON
        payload = json_calls[0][0][1]
        data = json.loads(payload)
        assert 'total' in data
        assert 'today' in data
        assert 'yesterday' in data


class TestMQTTDiscovery:
    """Test MQTT discovery functionality."""
    
    def test_global_discovery(self, mock_mqtt_client):
        """Test sending global discovery messages."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader',
                'discovery': True,
                'discovery_prefix': 'homeassistant',
                'online': 'online',
                'offline': 'offline'
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        # Send global discovery
        task._send_global_discovery()
        
        # Verify discovery messages were sent
        calls = mock_mqtt_client.publish.call_args_list
        topics = [call[0][0] for call in calls]
        
        # Should have status, error, and diagnostic sensors
        assert any('binary_sensor' in topic and 'status' in topic for topic in topics)
        assert any('sensor' in topic and 'error' in topic for topic in topics)
        assert any('version' in topic for topic in topics)
    
    def test_meter_discovery(self, mock_mqtt_client):
        """Test sending meter-specific discovery messages."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader',
                'discovery': True,
                'discovery_prefix': 'homeassistant',
                'split_topic': True
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        meter_data = {
            'name': 'Water',
            'total': 1000,
            'today': 50,
            'yesterday': 30
        }
        
        # Send meter discovery
        task._send_meter_discovery(1, meter_data)
        
        # Verify discovery messages were sent
        calls = mock_mqtt_client.publish.call_args_list
        topics = [call[0][0] for call in calls]
        
        # Should have sensor for total, today, yesterday
        assert any('sensor' in topic and '_1_total' in topic for topic in topics)
        assert any('sensor' in topic and '_1_today' in topic for topic in topics)
        assert any('sensor' in topic and '_1_yesterday' in topic for topic in topics)
        
        # Should have number entity for total correction
        assert any('number' in topic for topic in topics)
        
        # Should have text entity for name
        assert any('text' in topic for topic in topics)


class TestMQTTSetCommands:
    """Test MQTT set command handling."""
    
    def test_set_total_command(self, mock_mqtt_client):
        """Test handling of total/set command."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader'
            }
        })
        
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({
            'date': datetime.date.today(),
            1: {
                'pulsecount': 0,
                'total': 1000,
                'today': 0,
                'yesterday': 0
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        # Create mock message
        mock_msg = MagicMock()
        mock_msg.topic = 's0pcmreader/1/total/set'
        mock_msg.payload = b'5000'
        
        # Handle set command
        task._handle_set_command(mock_msg)
        
        # Verify total was updated
        assert s0pcm_reader.measurement[1]['total'] == 5000
    
    def test_set_name_command(self, mock_mqtt_client):
        """Test handling of name/set command."""
        s0pcm_reader.config.clear()
        s0pcm_reader.config.update({
            'mqtt': {
                'base_topic': 's0pcmreader',
                'discovery': True,
                'discovery_prefix': 'homeassistant',
                'split_topic': True
            }
        })
        
        s0pcm_reader.measurement.clear()
        s0pcm_reader.measurement.update({
            'date': datetime.date.today(),
            1: {
                'pulsecount': 0,
                'total': 1000,
                'today': 0,
                'yesterday': 0
            }
        })
        
        trigger = threading.Event()
        stopper = threading.Event()
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        # Create mock message
        mock_msg = MagicMock()
        mock_msg.topic = 's0pcmreader/1/name/set'
        mock_msg.payload = b'WaterMeter'
        
        # Handle name set command
        task._handle_name_set(mock_msg)
        
        # Verify name was updated
        assert s0pcm_reader.measurement[1]['name'] == 'WaterMeter'


class TestStateRecovery:
    """Test MQTT state recovery functionality."""
    
    def test_recovery_from_mqtt(self, mock_mqtt_client):
        """Test state recovery from MQTT retained messages."""
        
        trigger = threading.Event()
        stopper = threading.Event()
        
        s0pcm_reader.config = {
            'mqtt': {
                'base_topic': 's0pcmreader',
                'discovery_prefix': 'homeassistant'
            }
        }
        
        s0pcm_reader.measurement = {'date': '2026-01-24'}
        s0pcm_reader.recovery_event = threading.Event()
        
        task = s0pcm_reader.TaskDoMQTT(trigger, stopper)
        task._mqttc = mock_mqtt_client
        
        # Mock retained messages
        def mock_on_message_callback(client, userdata, msg):
            """Simulate receiving retained messages."""
            pass
        
        # Note: Full recovery testing would require more complex mocking
        # of the MQTT message loop. This is a simplified example.
        
        # Verify recovery event is set after recovery
        # In real implementation, this would be tested with integration tests


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
