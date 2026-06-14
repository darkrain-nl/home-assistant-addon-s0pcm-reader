"""
Tests for configuration loading and validation.
"""

import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

import config as config_module
import state as state_module


@pytest.fixture(autouse=True)
def setup_config_test_env():
    # No global configdirectory to reset anymore
    pass


class TestConfigLoading:
    def test_load_default_config(self, mocker):
        # Mock Path.exists and Path.read_text for safer modern python testing
        mocker.patch.object(Path, "exists", return_value=False)
        context = state_module.get_context()
        context.config = config_module.read_config()
        assert context.config.mqtt.host == "127.0.0.1"

    def test_load_config_from_options(self, sample_options, mocker):
        mocker.patch.object(Path, "exists", return_value=True)
        mocker.patch.object(Path, "read_text", return_value=json.dumps(sample_options))
        context = state_module.get_context()
        context.config = config_module.read_config()
        assert context.config.mqtt.host == sample_options["mqtt"]["host"]


class TestCLI:
    def test_init_args_custom(self, mocker):
        # init_args was inlined; test config_module.init_args directly
        with patch.object(sys, "argv", ["s0pcm_reader", "--config", "/custom/path"]):
            path = config_module.init_args()
            assert path == Path("/custom/path")


class TestConfigEdgeCases:
    def test_tls_path_join(self, mocker):
        mocker.patch.object(Path, "exists", return_value=True)
        mocker.patch.object(Path, "read_text", return_value=json.dumps({"security": {"tls": True, "tls_ca": "ca.crt"}}))
        context = state_module.get_context()
        context.config = config_module.read_config(config_dir=Path("/data/"))
        expected_path = os.path.normpath("data/ca.crt")
        actual_path = os.path.normpath(context.config.mqtt.tls_ca)
        assert expected_path in actual_path

    def test_password_redaction(self, mocker):
        mocker.patch.object(Path, "exists", return_value=True)
        # Test 1: Password set
        mocker.patch.object(
            Path, "read_text", return_value=json.dumps({"mqtt": {"password": "secret", "username": "admin"}})
        )
        with patch("logging.Logger.debug") as mock_debug:
            config_module.read_config()
            log_str = str(mock_debug.call_args[0][0])
            assert "**********" in log_str
            assert "secret" not in log_str
            assert "admin" not in log_str

        # Test 2: Password None
        mocker.patch.object(Path, "read_text", return_value=json.dumps({}))
        with patch("logging.Logger.debug") as mock_debug:
            config_module.read_config()
            log_str = str(mock_debug.call_args[0][0])
            # Check for None explicitly
            assert "'password': None" in log_str
            assert "'username': None" in log_str


class TestErrorHandling:
    def test_set_error_behavior(self, mocker):
        """Test SetError sets the shared error and triggers the event, including clearing."""
        context = state_module.get_context()
        context.lasterror_share = None
        context.lasterror_serial = None
        context.lasterror_mqtt = None

        # 1. Set error
        context.set_error("Test Error")
        assert context.lasterror_share == "Test Error"
        assert context.trigger_event.is_set()

        context.trigger_event.clear()
        context.set_error(None)
        assert context.lasterror_share is None
        assert context.trigger_event.is_set()


class TestConfigCoverage:
    def test_read_config_options_exception(self):
        """Test exception handling during options.json load (lines 118-119)."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", side_effect=Exception("Read Error")),
            patch("config.logger.error") as mock_logger,
        ):
            config_module.read_config()
            assert mock_logger.called
            assert "Failed to load" in mock_logger.call_args[0][0]

    def test_read_config_mqtt_discovery_log(self, mocker):
        """Test logging when MQTT service discovery is used (line 126)."""
        # Mock get_supervisor_config to return data
        with (
            patch("config.get_supervisor_config", return_value={"host": "1.2.3.4"}),
            patch("config.logger.info") as mock_logger,
        ):
            config_module.read_config()

            # One of the calls should be the discovery message
            found = any("Using MQTT service discovery" in str(c) for c in mock_logger.call_args_list)
            assert found

    def test_read_config_returns_model(self):
        """Test that read_config returns a ConfigModel directly."""
        model = config_module.read_config()
        assert model.mqtt.base_topic == "s0pcmreader"
        assert model.log.level == "INFO"

    def test_read_config_mqtt_version_string(self):
        """Test that MQTT version is stored as a string."""
        model = config_module.read_config()
        assert model.mqtt.version == "5.0"
        assert isinstance(model.mqtt.version, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
