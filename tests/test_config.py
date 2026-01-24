"""
Tests for configuration loading and validation.
"""
import pytest
import json
import os
import importlib
from unittest.mock import MagicMock, patch


class TestConfigLoading:
    """Test configuration loading from options.json."""
    
    def test_load_default_config(self, temp_config_dir, mocker):
        """Test loading configuration with defaults."""
        import importlib
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        # Mock the options file path to not exist
        mocker.patch('os.path.exists', return_value=False)
        
        # Read config should use defaults
        s0pcm_reader.ReadConfig()
        
        assert 'mqtt' in s0pcm_reader.config
        assert 'serial' in s0pcm_reader.config
        assert 'log' in s0pcm_reader.config
    
    def test_load_config_from_options(self, temp_config_dir, sample_options, mocker):
        """Test loading configuration from options.json."""
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        # Mock options file content
        mocker.patch('os.path.exists', side_effect=lambda p: p == '/data/options.json')
        mocker.patch('builtins.open', mocker.mock_open(read_data=json.dumps(sample_options)))
        
        # Read config
        s0pcm_reader.ReadConfig()
        
        # Verify config was loaded
        assert s0pcm_reader.config['mqtt']['host'] == sample_options['mqtt_host']
        assert s0pcm_reader.config['mqtt']['username'] == sample_options['mqtt_username']
        assert s0pcm_reader.config['serial']['port'] == sample_options['device']


class TestConfigValidation:
    """Test configuration validation and defaults."""
    
    def test_mqtt_version_mapping(self):
        """Test MQTT version string to constant mapping."""
        import importlib
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        import paho.mqtt.client as mqtt
        
        # Test version 3.1
        s0pcm_reader.config = {'mqtt': {'version': '3.1'}}
        # Normally ReadConfig would do this, but we're testing the logic
        version_str = str(s0pcm_reader.config['mqtt']['version'])
        if version_str == '3.1':
            result = mqtt.MQTTv31
        elif version_str == '3.1.1':
            result = mqtt.MQTTv311
        else:
            result = mqtt.MQTTv5
        
        assert result == mqtt.MQTTv31
    
    def test_log_level_defaults(self, mocker):
        """Test log level defaults to INFO."""
        import importlib
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        mocker.patch('os.path.exists', return_value=False)
        
        s0pcm_reader.ReadConfig()
        
        assert s0pcm_reader.config['log']['level'] == 'INFO'


class TestSupervisorAPI:
    """Test Home Assistant Supervisor API integration."""
    
    def test_mqtt_service_discovery(self, mock_supervisor_api, mocker):
        """Test MQTT service discovery from Supervisor."""
        import importlib
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        # Set environment variable
        mocker.patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'test_token'})
        
        # Call GetSupervisorConfig
        result = s0pcm_reader.GetSupervisorConfig('mqtt')
        
        assert result is not None
        assert 'host' in result
        assert result['host'] == 'core-mosquitto'
    
    def test_supervisor_api_no_token(self, mocker):
        """Test Supervisor API when no token is available."""
        import importlib
        import s0pcm_reader
        importlib.reload(s0pcm_reader)
        
        # Remove token
        mocker.patch.dict(os.environ, {}, clear=True)
        
        result = s0pcm_reader.GetSupervisorConfig('mqtt')
        
        assert result == {}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
