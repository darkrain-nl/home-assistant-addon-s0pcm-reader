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

@pytest.fixture(autouse=True)
def reset_globals():
    s0pcm_reader.config.clear()
    s0pcm_reader.measurement.clear()
    s0pcm_reader.measurement['date'] = '2026-01-24'
    s0pcm_reader.configdirectory = './'

class TestConfigLoading:
    def test_load_default_config(self, mocker):
        # Mock Path.exists and Path.read_text for safer modern python testing
        mocker.patch.object(Path, 'exists', return_value=False)
        s0pcm_reader.ReadConfig()
        assert 'mqtt' in s0pcm_reader.config
        assert s0pcm_reader.config['mqtt']['host'] == '127.0.0.1'
    
    def test_load_config_from_options(self, sample_options, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps(sample_options))
        s0pcm_reader.ReadConfig()
        assert s0pcm_reader.config['mqtt']['host'] == sample_options['mqtt_host']

class TestCLI:
    def test_init_args_custom(self, mocker):
        # Use patch.object on sys.argv
        with patch.object(sys, 'argv', ['s0pcm_reader', '--config', '/custom/path']):
            s0pcm_reader.init_args()
            assert '/custom/path/' in s0pcm_reader.configdirectory

class TestConfigEdgeCases:
    def test_tls_path_join(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps({"mqtt_tls": True, "mqtt_tls_ca": "ca.crt"}))
        s0pcm_reader.configdirectory = "/data/"
        s0pcm_reader.ReadConfig()
        expected_path = os.path.normpath("data/ca.crt")
        actual_path = os.path.normpath(s0pcm_reader.config['mqtt']['tls_ca'])
        assert expected_path in actual_path

    def test_password_redaction(self, mocker):
        mocker.patch.object(Path, 'exists', return_value=True)
        mocker.patch.object(Path, 'read_text', return_value=json.dumps({"mqtt_password": "secret"}))
        with patch('logging.Logger.debug') as mock_debug:
            s0pcm_reader.ReadConfig()
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
        s0pcm_reader.trigger = threading.Event()
        s0pcm_reader.lasterrorshare = None
        
        # 1. Set error
        s0pcm_reader.SetError("Test Error")
        assert s0pcm_reader.lasterrorshare == "Test Error"
        assert s0pcm_reader.trigger.is_set()
        
        # 2. Clear error
        s0pcm_reader.trigger.clear()
        s0pcm_reader.SetError(None)
        assert s0pcm_reader.lasterrorshare is None
        assert s0pcm_reader.trigger.is_set()

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
