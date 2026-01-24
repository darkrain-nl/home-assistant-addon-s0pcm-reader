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

@pytest.fixture(autouse=True)
def reset_globals():
    s0pcm_reader.config.clear()
    s0pcm_reader.measurement.clear()
    s0pcm_reader.measurement['date'] = datetime.date.today()
    s0pcm_reader.measurementshare.clear()
    s0pcm_reader.lasterrorshare = None
    s0pcm_reader.s0pcmreaderversion = "dev"
    # Provide enough config for TaskDoMQTT.__init__
    s0pcm_reader.config.update({
        'mqtt': {
            'base_topic': 's0', 
            'discovery_prefix': 'ha',
            'online': 'on',
            'offline': 'off',
            'retain': True,
            'client_id': None,
            'version': 5
        }
    })

class TestMQTTConnection:
    def test_mqtt_connect_success(self, mock_mqtt_client, mocker):
        task = s0pcm_reader.TaskDoMQTT(threading.Event(), threading.Event())
        task._mqttc = mock_mqtt_client
        task.on_connect(mock_mqtt_client, None, None, 0, None)
        assert task._connected is True

class TestMQTTPublish:
    def test_publish_measurements(self, mock_mqtt_client):
        s0pcm_reader.config['mqtt']['split_topic'] = True
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
        
        assert 1 in s0pcm_reader.measurement
        assert s0pcm_reader.measurement[1]['total'] == 123
        assert 2 in s0pcm_reader.measurement
        assert s0pcm_reader.measurement[2]['total'] == 456

class TestMQTTSetCommands:
    def test_handle_set_command(self):
        s0pcm_reader.measurement[1] = {'total': 0}
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._handle_set_command(MagicMock(topic='s0/1/total/set', payload=b'500'))
        assert s0pcm_reader.measurement[1]['total'] == 500

    def test_handle_name_set(self, mock_mqtt_client):
        s0pcm_reader.measurement[1] = {'total': 0}
        task = s0pcm_reader.TaskDoMQTT(None, None)
        task._mqttc = mock_mqtt_client
        task._handle_name_set(MagicMock(topic='s0/1/name/set', payload=b'Kitchen'))
        assert s0pcm_reader.measurement[1]['name'] == 'Kitchen'

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
