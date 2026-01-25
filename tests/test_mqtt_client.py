"""
Tests for MQTT client functionality.
"""
import pytest
import threading
import time
import json
import datetime
import re
import sys
from unittest.mock import MagicMock, patch
import s0pcm_reader
import state as state_module
import mqtt_handler
import config as config_module

@pytest.fixture(autouse=True)
def setup_mqtt_config():
    # state_module.config/measurement cleared by conftest.py
    
    # Initialize basic MQTT config using the standard read_config logic
    config_module.read_config(state_module.config, "test")
    state_module.s0pcmreaderversion = "dev"
    
    # Override keys specifically needed for tests
    state_module.config['mqtt'].update({
        'base_topic': 's0',
        'discovery_prefix': 'ha',
        'client_id': None
    })

@pytest.fixture
def mock_mqtt_client(mocker):
    # Patch the mqtt module in mqtt_handler
    mock_mqtt = mocker.patch('mqtt_handler.mqtt')
    mock_client = MagicMock()
    mock_mqtt.Client.return_value = mock_client
    return mock_client

class TestMQTTConnection:
    def test_mqtt_connect_success(self, mock_mqtt_client, mocker):
        task = s0pcm_reader.TaskDoMQTT(threading.Event(), threading.Event())
        task._mqttc = mock_mqtt_client
        task.on_connect(mock_mqtt_client, None, None, 0, None)
        assert task._connected is True

class TestMQTTPublish:
    def test_publish_measurements(self, mock_mqtt_client):
        state_module.config['mqtt']['split_topic'] = True
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client
        task._publish_measurements({1: {'name': 'Water', 'total': 100}}, {})
        assert any('s0/Water/total' in str(c) for c in mock_mqtt_client.publish.call_args_list)

class TestStateRecovery:
    def test_recover_state_logic(self, mock_mqtt_client, mocker):
        mocker.patch('time.sleep')
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client
        
        def trigger_msgs(*args, **kwargs):
            cb = mock_mqtt_client.on_message
            if cb:
                # 1. Config -> ID 1 mapped to 'Water' (Regex expects s0pcm_BASE_ID_...)
                cb(mock_mqtt_client, None, MagicMock(topic='ha/sensor/s0/s0pcm_s0_1_total/config', 
                    payload=json.dumps({'unique_id': 's0pcm_s0_1_total', 'state_topic': 's0/Water/total'}).encode()))
                # 2. Data for 'Water' (mapped to 1)
                cb(mock_mqtt_client, None, MagicMock(topic='s0/Water/total', payload=b'123'))
                # 3. Data for '2' (directly numeric)
                cb(mock_mqtt_client, None, MagicMock(topic='s0/2/total', payload=b'456'))
        
        mock_mqtt_client.subscribe.side_effect = trigger_msgs
        task._recover_state()
        
        assert 1 in state_module.measurement
        assert state_module.measurement[1]['total'] == 123
        assert 2 in state_module.measurement
        assert state_module.measurement[2]['total'] == 456

class TestMQTTSetCommands:
    def test_handle_set_command(self):
        state_module.measurement[1] = {'total': 0}
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._handle_set_command(MagicMock(topic='s0/1/total/set', payload=b'500'))
        assert state_module.measurement[1]['total'] == 500

    def test_handle_name_set(self, mock_mqtt_client):
        state_module.measurement[1] = {'total': 0}
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client
        task._handle_name_set(MagicMock(topic='s0/1/name/set', payload=b'Kitchen'))
        assert state_module.measurement[1]['name'] == 'Kitchen'
        # Name clearing
        with patch('state.SaveMeasurement') as mock_save:
            task._handle_name_set(MagicMock(topic='s0/1/name/set', payload=b''))
            assert 'name' not in state_module.measurement[1]
            assert mock_save.called

def test_mqtt_handler_error_cases(mocker):
    """Test error handling in MQTT message processing."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    state_module.measurement = {1: {'total': 100}}
    
    # 1. Unknown identifier (not ID, not Name)
    with patch('state.SetError') as mock_err:
        task._handle_set_command(MagicMock(topic='s0/UnknownMeter/total/set', payload=b'500'))
        assert mock_err.called
        assert "unknown meter ID" in str(mock_err.call_args)
        
    # 2. Invalid payload (non-numeric)
    with patch('state.SetError') as mock_err:
        task._handle_set_command(MagicMock(topic='s0/1/total/set', payload=b'ABC'))
        assert mock_err.called
        assert "invalid payload" in str(mock_err.call_args)
        
    # 3. Unknown name in set
    with patch('state.SetError') as mock_err:
        task._handle_set_command(MagicMock(topic='s0/NonExistent/total/set', payload=b'500'))
        assert mock_err.called

def test_mqtt_callbacks(mocker):
    """Test standard MQTT callbacks."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    task._mqttc = MagicMock()
    
    # on_connect failure
    with patch('state.SetError') as mock_set:
        task.on_connect(None, None, None, 5, None)  # 5 is unauthorized
        assert mock_set.called
    
    # on_disconnect
    task.on_disconnect(None, None, None, 0, None)
    assert not task._connected
    
    # on_log (should just pass)
    task.on_log(None, None, 1, "test log") # level 1

def test_publish_measurements_json(mocker):
    """Test MQTT publication in JSON mode (split_topic=False)."""
    task = s0pcm_reader.TaskDoMQTT(MagicMock(), MagicMock())
    state_module.config['mqtt']['split_topic'] = False
    state_module.config['mqtt']['base_topic'] = 's0'
    state_module.config['mqtt']['retain'] = True
    
    task._mqttc = MagicMock()
    
    measurementlocal = {1: {'name': 'Water', 'total': 100, 'today': 5, 'yesterday': 2}}
    measurementprevious = {}
    
    task._publish_measurements(measurementlocal, measurementprevious)
    
    # Check if JSON was published to s0/Water
    json_call = [c for c in task._mqttc.publish.call_args_list if 's0/Water' in str(c)]
    assert json_call
    payload = json.loads(json_call[0][0][1])
    assert payload['total'] == 100
    assert payload['today'] == 5

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
