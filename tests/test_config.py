"""
Tests for configuration loading and validation.
"""
import pytest
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import s0pcm_reader
import config as config_module
import state as state_module

@pytest.fixture(autouse=True)
def setup_config_test_env():
    # Context and state are reset by conftest.py
    config_module.configdirectory = './'

class TestConfigLoading:
    def test_load_default_config(self, mocker):
        # Mock Path.exists and Path.read_text for safer modern python testing
        mocker.patch.object(Path, 'exists', return_value=False)
        context = state_module.get_context()
        context.config = config_module.read_config().model_dump()
        assert 'mqtt' in context.config
        assert context.config['mqtt']['host'] == '127.0.0.1'
    
    def test_load_config_from_options(self, sample_options, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps(sample_options))
        context = state_module.get_context()
        context.config = config_module.read_config().model_dump()
        assert context.config['mqtt']['host'] == sample_options['mqtt_host']

class TestCLI:
    def test_init_args_custom(self, mocker):
        # Use patch.object on sys.argv
        with patch.object(sys, 'argv', ['s0pcm_reader', '--config', '/custom/path']):
            s0pcm_reader.init_args()
            assert '/custom/path/' in config_module.configdirectory

class TestConfigEdgeCases:
    def test_tls_path_join(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps({"mqtt_tls": True, "mqtt_tls_ca": "ca.crt"}))
        config_module.configdirectory = "/data/"
        context = state_module.get_context()
        context.config = config_module.read_config().model_dump()
        expected_path = os.path.normpath("data/ca.crt")
        actual_path = os.path.normpath(context.config['mqtt']['tls_ca'])
        assert expected_path in actual_path

    def test_password_redaction(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps({"mqtt_password": "secret"}))
        with patch('logging.Logger.debug') as mock_debug:
            config_module.read_config()
            # The redacted version should be in THE LOGS
            found = False
            for call in mock_debug.call_args_list:
                if '********' in str(call):
                    found = True
                    break
            assert found
            assert not any('secret' in str(c) for c in mock_debug.call_args_list)

class TestErrorHandling:
    def test_set_error_behavior(self, mocker):
        """Test SetError sets the shared error and triggers the event, including clearing."""
        trigger = threading.Event()
        context = state_module.get_context()
        context.register_trigger(trigger)
        context.lasterror_share = None
        context.lasterror_serial = None # Reset internal state too
        context.lasterror_mqtt = None
        
        # 1. Set error
        context.set_error("Test Error")
        assert context.lasterror_share == "Test Error"
        assert trigger.is_set()
        
        # 2. Clear error
        trigger.clear()
        context.set_error(None)
        assert context.lasterror_share is None
        assert trigger.is_set()

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
