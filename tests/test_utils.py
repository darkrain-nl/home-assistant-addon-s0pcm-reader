"""
Tests for helper modules (utils.py).
"""

import json
import os
from unittest.mock import MagicMock

import pytest

import utils


def test_get_version_from_env(mocker):
    """Test get_version from environment variable."""
    mocker.patch.dict(os.environ, {"S0PCM_READER_VERSION": "3.1.0"})
    assert utils.get_version() == "3.1.0"


def test_get_version_fallback(mocker):
    """Test GetVersion fallback when env is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("os.path.exists", return_value=False)
    assert utils.get_version() == "dev"


def test_get_version_config_yaml(mocker, temp_config_dir):
    """Test GetVersion reading from config.yaml."""
    mocker.patch.dict(os.environ, {}, clear=True)

    config_path = os.path.join(temp_config_dir, "config.yaml")
    with open(config_path, "w") as f:
        f.write("version: '3.0.0-test'\n")

    # Surgical mock: only our temp file exists
    mocker.patch("utils.os.path.exists", side_effect=lambda p: p == config_path)
    # Ensure search_paths includes our temp file by mocking the first join
    mocker.patch(
        "utils.os.path.join", side_effect=lambda *args: config_path if "config.yaml" in args[-1] else "/".join(args)
    )

    version = utils.get_version()
    assert "3.0.0-test" in version


def test_get_version_invalid_yaml(mocker, temp_config_dir):
    """Test get_version handles invalid YAML gracefully."""
    mocker.patch.dict(os.environ, {}, clear=True)

    config_path = os.path.join(temp_config_dir, "config.yaml")
    with open(config_path, "w") as f:
        f.write("{invalid yaml: [}")

    mocker.patch("utils.os.path.exists", side_effect=lambda p: p == config_path)
    mocker.patch(
        "utils.os.path.join", side_effect=lambda *args: config_path if "config.yaml" in args[-1] else "/".join(args)
    )

    # Should fall back to 'dev' because our file is invalid
    assert utils.get_version() == "dev"


def test_get_version_yaml_no_version_key(mocker, temp_config_dir):
    """Test get_version when YAML exists but has no version key."""
    mocker.patch.dict(os.environ, {}, clear=True)

    config_path = os.path.join(temp_config_dir, "config.yaml")
    with open(config_path, "w") as f:
        f.write("name: 'S0PCM Reader'\n")

    mocker.patch("utils.os.path.exists", side_effect=lambda p: p == config_path)
    mocker.patch(
        "utils.os.path.join", side_effect=lambda *args: config_path if "config.yaml" in args[-1] else "/".join(args)
    )

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
    mocker.patch("urllib.request.urlopen", side_effect=Exception("API Error"))

    result = utils.get_supervisor_config("mqtt")

    assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
