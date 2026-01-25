"""
Tests for discovery module (discovery.py).
"""
import pytest
import json
from unittest.mock import MagicMock
import discovery
import state as state_module

def test_send_global_discovery(mocker):
    """Test global discovery message publishing."""
    mock_mqttc = MagicMock()
    state_module.config['mqtt'] = {
        'discovery': True,
        'base_topic': 's0pcm',
        'discovery_prefix': 'homeassistant',
        'online': 'online',
        'offline': 'offline'
    }
    state_module.s0pcmreaderversion = '3.0.0'
    
    discovery.send_global_discovery(mock_mqttc)
    
    # Core check: Was something published?
    assert mock_mqttc.publish.called
    
    # Check status topic
    status_call = [c for c in mock_mqttc.publish.call_args_list if 'binary_sensor/s0pcm/s0pcm_s0pcm_status/config' in str(c)]
    assert status_call
    payload = json.loads(status_call[0][0][1])
    assert payload['name'] == "S0PCM Reader Status"
    assert payload['device']['sw_version'] == '3.0.0'

def test_send_meter_discovery(mocker):
    """Test meter discovery message publishing."""
    mock_mqttc = MagicMock()
    state_module.config['mqtt'] = {
        'discovery': True,
        'base_topic': 's0pcm',
        'discovery_prefix': 'homeassistant',
        'split_topic': True
    }
    
    meter_data = {'name': 'Water'}
    instancename = discovery.send_meter_discovery(mock_mqttc, 1, meter_data)
    
    assert instancename == 'Water'
    
    # Check total sensor discovery
    total_call = [c for c in mock_mqttc.publish.call_args_list if 'sensor/s0pcm/s0pcm_s0pcm_1_total/config' in str(c)]
    assert total_call
    payload = json.loads(total_call[-1][0][1]) # Get last call for this topic
    assert payload['name'] == "Water Total"
    assert payload['state_class'] == 'total_increasing'

def test_discovery_disabled(mocker):
    """Test behavior when discovery is disabled."""
    mock_mqttc = MagicMock()
    state_module.config['mqtt'] = {'discovery': False}
    
    discovery.send_global_discovery(mock_mqttc)
    assert not mock_mqttc.publish.called
    
    result = discovery.send_meter_discovery(mock_mqttc, 1, {})
    assert result is None
    assert not mock_mqttc.publish.called
