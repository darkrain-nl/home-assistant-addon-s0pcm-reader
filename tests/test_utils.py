"""
Tests for helper modules (utils.py).
"""

import json
import os
from unittest.mock import MagicMock
import urllib.error

import pytest

import utils


async def test_get_version_from_env(mocker):
    """Test get_version from environment variable."""
    mocker.patch.dict(os.environ, {"S0PCM_READER_VERSION": "3.1.0"})
    assert await utils.get_version() == "3.1.0"


async def test_get_version_fallback(mocker, tmp_path, monkeypatch):
    """Test GetVersion fallback when env is missing and no config file."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)
    # Mock __file__ to point to our tmp_path
    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))
    assert await utils.get_version() == "dev"


async def test_get_version_config_yaml(mocker, tmp_path, monkeypatch):
    """Test GetVersion reading from config.yaml."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("version: '3.0.0-test'\n", encoding="utf-8")

    # Mock __file__ so utils looks in tmp_path
    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    version = await utils.get_version()
    assert "3.0.0-test" in version


async def test_get_version_invalid_yaml(mocker, tmp_path, monkeypatch):
    """Test get_version handles invalid YAML gracefully."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("{invalid yaml: [}", encoding="utf-8")

    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    # Should fall back to 'dev' because our file is invalid
    assert await utils.get_version() == "dev"


async def test_get_version_yaml_no_version_key(mocker, tmp_path, monkeypatch):
    """Test get_version when YAML exists but has no version key."""
    monkeypatch.chdir(tmp_path)
    mocker.patch.dict(os.environ, {}, clear=True)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("name: 'S0PCM Reader'\n", encoding="utf-8")

    mocker.patch("utils.__file__", str(tmp_path / "utils.py"))

    assert await utils.get_version() == "dev"


async def test_get_supervisor_config_no_token(mocker):
    """Test GetSupervisorConfig when token is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    assert await utils.get_supervisor_config("mqtt") == {}


async def test_get_supervisor_config_success(mocker):
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

    result = await utils.get_supervisor_config("mqtt")

    assert result["host"] == "core-mosquitto"
    assert result["port"] == 1883
    assert result["username"] == "mqtt_user"


async def test_get_supervisor_config_api_error(mocker):
    """Test Supervisor API handles errors gracefully."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    # Raise URLError which is one of the caught exceptions
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("API Error"))

    result = await utils.get_supervisor_config("mqtt")

    assert result == {}


async def test_get_supervisor_config_status_not_200(mocker):
    """Test Supervisor API returns empty dict when response status is not 200."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    mock_response = MagicMock()
    mock_response.status = 204
    mock_response.__enter__ = lambda self: self
    mock_response.__exit__ = lambda self, *args: None
    mocker.patch("urllib.request.urlopen", return_value=mock_response)

    result = await utils.get_supervisor_config("mqtt")
    assert result == {}


# ------------------------------------------------------------------------------------
# HA Core Version Tests
# ------------------------------------------------------------------------------------


async def test_get_ha_core_version_no_token(mocker):
    """Test get_ha_core_version when token is missing."""
    mocker.patch.dict(os.environ, {}, clear=True)
    assert await utils.get_ha_core_version() is None


async def test_get_ha_core_version_success(mocker):
    """Test successful HA core version fetch."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"data": {"version": "2025.5.0"}}).encode()
    mock_response.__enter__ = lambda self: self
    mock_response.__exit__ = lambda self, *args: None
    mocker.patch("urllib.request.urlopen", return_value=mock_response)

    assert await utils.get_ha_core_version() == "2025.5.0"


async def test_get_ha_core_version_error(mocker):
    """Test get_ha_core_version handles errors gracefully."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("API Error"))
    assert await utils.get_ha_core_version() is None


async def test_get_ha_core_version_status_not_200(mocker):
    """Test get_ha_core_version returns None when response status is not 200."""
    mocker.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "test_token"})
    mock_response = MagicMock()
    mock_response.status = 204
    mock_response.__enter__ = lambda self: self
    mock_response.__exit__ = lambda self, *args: None
    mocker.patch("urllib.request.urlopen", return_value=mock_response)

    assert await utils.get_ha_core_version() is None


def test_parse_ha_version():
    """Test HA version string parsing."""
    assert utils.parse_ha_version("2025.5.0") == (2025, 5, 0)
    assert utils.parse_ha_version("2025.5.0b1") == (2025, 5, 0)
    assert utils.parse_ha_version("2025") == (2025,)
    assert utils.parse_ha_version("2025.5.beta") == (2025, 5, 0)
    assert utils.parse_ha_version("dev") == (0,)
    assert utils.parse_ha_version(None) == (0, 0, 0)
    assert utils.parse_ha_version("") == (0, 0, 0)


# ------------------------------------------------------------------------------------
# Parse Localized Number Tests
# ------------------------------------------------------------------------------------


def test_parse_localized_number_simple():
    """Test standard number parsing."""
    assert utils.parse_localized_number("1000") == 1000.0
    assert utils.parse_localized_number("1000.5") == 1000.5
    assert utils.parse_localized_number("-50") == -50.0


def test_parse_localized_number_units():
    """Test parsing numbers with units."""
    assert utils.parse_localized_number("1000 kWh") == 1000.0
    assert utils.parse_localized_number("500.5 m³") == 500.5
    assert utils.parse_localized_number("12 l/min") == 12.0


def test_parse_localized_number_us_format():
    """Test parsing US formatted numbers (dots for decimal, commas for thousands)."""
    assert utils.parse_localized_number("1,000.50") == 1000.5
    assert utils.parse_localized_number("1,000,000.00") == 1000000.0
    # Ambiguous single comma: Code defaults to treating single comma as decimal (EU preference/Safety)
    # So 1,500 -> 1.5
    assert utils.parse_localized_number("1,500") == 1.5


def test_parse_localized_number_eu_format():
    """Test parsing EU formatted numbers (commas for decimal, dots for thousands)."""
    assert utils.parse_localized_number("1.000,50") == 1000.5
    assert utils.parse_localized_number("1.000.000,00") == 1000000.0
    # Ambiguous single dot: Code defaults to treating single dot as decimal (US preference/Standard float)
    # So 1.500 -> 1.5
    assert utils.parse_localized_number("1.500") == 1.5


def test_parse_localized_number_ambiguous():
    """Test ambiguous cases."""
    # Single comma, no dot -> usually decimal in EU if not obviously thousands
    # But our logic prefers decimal if single comma and no dot
    assert utils.parse_localized_number("1000,5") == 1000.5
    assert utils.parse_localized_number("0,5") == 0.5

    # Mixed or chaotic
    assert utils.parse_localized_number("1.000.000") == 1000000.0  # Assumes thousands
    # 1.1.1,1,1 -> should strip separators and parse
    assert utils.parse_localized_number("1.1.1,1,1") == 11111.0


def test_parse_localized_number_invalid():
    """Test invalid inputs."""
    assert utils.parse_localized_number(None) is None
    assert utils.parse_localized_number("") is None
    assert utils.parse_localized_number("abc") is None
    assert utils.parse_localized_number("unknown") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
