"""
Tests for helper modules (utils.py and state.py).
"""
import os
import pytest
import datetime
from unittest.mock import MagicMock, patch
import utils
import state as state_module

def test_get_version_fallback(mocker):
    """Test GetVersion fallback when env is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch('os.path.exists', return_value=False)
    assert utils.get_version() == 'dev'

def test_get_version_config_yaml(mocker, temp_config_dir):
    """Test GetVersion reading from config.yaml."""
    mocker.patch.dict(os.environ, {}, clear=True)
    
    config_path = os.path.join(temp_config_dir, 'config.yaml')
    with open(config_path, 'w') as f:
        f.write("version: '3.0.0-test'\n")
    
    # Mock the search paths to include our temp file
    mocker.patch('utils.os.path.abspath', return_value='/tmp')
    mocker.patch('utils.os.path.dirname', return_value='/tmp')
    mocker.patch('utils.os.path.join', return_value=config_path)
    mocker.patch('utils.os.path.exists', return_value=True)
    
    version = utils.get_version()
    assert '3.0.0-test' in version

def test_get_supervisor_config_no_token(mocker):
    """Test GetSupervisorConfig when token is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    assert utils.get_supervisor_config('mqtt') == {}

def test_state_set_error_caching():
    """Test SetError behavior and shared state update."""
    state_module.lasterror_serial = None
    state_module.lasterror_mqtt = None
    
    # Set serial error
    state_module.SetError("Serial Fail", category='serial')
    assert state_module.lasterrorshare == "Serial Fail"
    
    # Set mqtt error (should join)
    state_module.SetError("MQTT Fail", category='mqtt')
    assert "Serial Fail" in state_module.lasterrorshare
    assert "MQTT Fail" in state_module.lasterrorshare
    
    # Clear serial error
    state_module.SetError(None, category='serial')
    assert state_module.lasterrorshare == "MQTT Fail"
    
    # Clear all
    state_module.SetError(None, category='mqtt')
    assert state_module.lasterrorshare is None

def test_state_read_measurement_corrupt(mocker, temp_config_dir):
    """Test ReadMeasurement with corrupt JSON."""
    bad_path = os.path.join(temp_config_dir, 'corrupt.json')
    with open(bad_path, 'w') as f:
        f.write("{invalid json")
    
    mocker.patch('state.config_module.measurementname', bad_path)
    state_module.read_measurement()
    # Should fallback to default today's date
    assert 'date' in state_module.measurement
    assert isinstance(state_module.measurement['date'], datetime.date)

def test_state_read_measurement_invalid_date(mocker, temp_config_dir):
    """Test ReadMeasurement with invalid date string."""
    path = os.path.join(temp_config_dir, 'bad_date.json')
    with open(path, 'w') as f:
        f.write('{"date": "not-a-date", "1": {"total": 100}}')
    
    mocker.patch('state.config_module.measurementname', path)
    state_module.read_measurement()
    assert state_module.measurement[1]['total'] == 100
    assert state_module.measurement['date'] == datetime.date.today()
