"""
Tests for helper modules (utils.py).
"""

import json
import os
from unittest.mock import MagicMock
import urllib.error

import pytest

import utils


def test_get_version_from_env(mocker):
    """Test get_version from environment variable."""
    mocker.patch.dict(os.environ, {"S0PCM_READER_VERSION": "3.1.0"})
    assert utils.get_version() == "3.1.0"


def test_get_version_fallback(mocker, tmp_path, monkeypatch):
    """Test GetVersion fallback when env is missing and no config file."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)
    # Mock __file__ to point to our tmp_path
    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))
    assert utils.get_version() == "dev"


def test_get_version_config_yaml(mocker, tmp_path, monkeypatch):
    """Test GetVersion reading from config.yaml."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("version: '3.0.0-test'\n", encoding="utf-8")

    # Mock __file__ so utils looks in tmp_path
    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    version = utils.get_version()
    assert "3.0.0-test" in version


def test_get_version_invalid_yaml(mocker, tmp_path, monkeypatch):
    """Test get_version handles invalid YAML gracefully."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("{invalid yaml: [}", encoding="utf-8")

    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    # Should fall back to 'dev' because our file is invalid
    assert utils.get_version() == "dev"


def test_get_version_yaml_no_version_key(mocker, tmp_path, monkeypatch):
    """Test get_version when YAML exists but has no version key."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("name: 'S0PCM Reader'\n", encoding="utf-8")

    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    assert utils.get_version() == "dev"


def test_get_supervisor_config_no_token(mocker):
    """Test GetSupervisorConfig when token is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    assert utils.get_supervisor_config("mqtt") == {}


def test_get_supervisor_config_success(mocker):
    """Test successful Supervisor API config fetch."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(
        {"data": {"host": "core-mosquitto", "port": 1883, "username": "mqtt_user", "password": "mqtt_pass"}}
    ).encode()
    mock_response.__enter__ = lambda self: self
    mock_response.__exit__ = lambda self, *args: None

    mocker.patch("urllib.request.urlopen", return_value=mock_response)

    result = utils.get_supervisor_config("mqtt")

    assert result["host"] == "core-mosquitto"
    assert result["port"] == 1883
    assert result["username"] == "mqtt_user"


def test_get_supervisor_config_api_error(mocker):
    """Test Supervisor API handles errors gracefully."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    # Raise URLError which is one of the caught exceptions
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("API Error"))

    result = utils.get_supervisor_config("mqtt")

    assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
