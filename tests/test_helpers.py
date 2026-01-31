"""
Tests for helper modules (utils.py and state.py).
"""

import datetime
import json
import os
from unittest.mock import MagicMock

import pytest

import state as state_module
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


def test_state_set_error_caching():
    """Test SetError behavior and shared state update."""
    context = state_module.get_context()
    context.lasterror_serial = None
    context.lasterror_mqtt = None
    context.lasterror_share = None

    # Set serial error
    context.set_error("Serial Fail", category="serial")
    assert context.lasterror_share == "Serial Fail"

    # Set mqtt error (should join)
    context.set_error("MQTT Fail", category="mqtt")
    assert "Serial Fail" in context.lasterror_share
    assert "MQTT Fail" in context.lasterror_share

    # Clear serial error
    context.set_error(None, category="serial")
    assert context.lasterror_share == "MQTT Fail"

    # Clear all
    context.set_error(None, category="mqtt")
    assert context.lasterror_share is None


def test_meter_state_dict_interface():
    """Test MeterState dict-like interface."""
    meter = state_module.MeterState(name="Water", total=1000, today=50)

    # Test __getitem__
    assert meter["name"] == "Water"
    assert meter["total"] == 1000

    # Test __setitem__
    meter["total"] = 1100
    assert meter.total == 1100

    # Test get
    assert meter.get("today") == 50
    assert meter.get("nonexistent", "default") == "default"

    # Test setdefault
    # 'yesterday' is 0 (not None), so setdefault should NOT overwrite it
    val = meter.setdefault("yesterday", 40)
    assert val == 0
    assert meter.yesterday == 0

    # Test setdefault on None field
    meter.name = None
    val = meter.setdefault("name", "DefaultName")
    assert val == "DefaultName"
    assert meter.name == "DefaultName"

    # Test keys, items, __contains__
    assert "name" in meter.keys()
    assert ("total", 1100) in meter.items()
    assert "name" in meter


def test_app_state_dict_interface():
    """Test AppState dict-like interface."""
    app_state = state_module.AppState()

    # Test __setitem__ with dict
    app_state[1] = {"total": 500, "today": 25}
    assert 1 in app_state.meters
    assert app_state.meters[1].total == 500

    # Test __getitem__
    assert app_state[1].total == 500
    assert app_state["date"] == datetime.date.today()

    # Test __contains__
    assert 1 in app_state
    assert "date" in app_state
    assert 99 not in app_state

    # Test update
    app_state.update({2: {"total": 300, "today": 15}})
    assert 2 in app_state.meters
    assert app_state[2].total == 300

    # Test keys, values, items
    keys = list(app_state.keys())
    assert 1 in keys
    assert "date" in keys

    # Test pop
    meter = app_state.pop(1)
    assert meter.total == 500
    assert 1 not in app_state.meters


def test_app_state_reset():
    """Test AppState reset_state method."""
    app_state = state_module.AppState()
    app_state[1] = {"total": 1000}
    app_state.date = datetime.date(2025, 1, 1)

    app_state.reset_state()

    assert len(app_state.meters) == 0
    assert app_state.date == datetime.date.today()


def test_app_context_initialization():
    """Test AppContext initialization."""
    context = state_module.AppContext()

    assert context.lock is not None
    assert context.recovery_event is not None
    assert isinstance(context.state, state_module.AppState)
    assert isinstance(context.state_share, state_module.AppState)
    assert context.lasterror_serial is None
    assert context.lasterror_mqtt is None
    assert context.s0pcm_firmware == "Unknown"


def test_app_context_register_trigger():
    """Test AppContext register_trigger method."""
    import threading

    context = state_module.AppContext()
    trigger = threading.Event()

    context.register_trigger(trigger)

    assert context.trigger_event is trigger


def test_app_context_set_error_with_trigger():
    """Test AppContext set_error triggers event."""
    import threading

    context = state_module.AppContext()
    trigger = threading.Event()
    context.register_trigger(trigger)

    context.set_error("Test Error", category="serial")

    assert trigger.is_set()
    assert context.lasterror_serial == "Test Error"


def test_app_context_deprecated_methods():
    """Test deprecated save/read measurement methods are no-ops."""
    context = state_module.AppContext()

    # Should not raise exceptions
    context.save_measurement()
    context.read_measurement()


def test_app_state_dict_extra():
    """Test AppState dict extras."""
    state = state_module.AppState()
    state.meters[1] = state_module.MeterState(name="Test")

    # Test get
    assert state.get("date") == state.date
    assert state.get(1).name == "Test"
    assert state.get(999, "MISSING") == "MISSING"

    # Test pop date (should return current and reset to today)
    old_date = datetime.date(2020, 1, 1)
    state.date = old_date
    popped = state.pop("date")
    assert popped == old_date
    assert state.date == datetime.date.today()

    # Test pop meter
    popped_meter = state.pop(1)
    assert popped_meter.name == "Test"
    assert 1 not in state
    assert state.pop(999, "NONE") == "NONE"


def test_meter_state_pop():
    """Test MeterState pop method."""
    meter = state_module.MeterState(name="Water", total=100)

    # Pop existing field (sets to None)
    val = meter.pop("name")
    assert val == "Water"
    assert meter.name is None

    # Pop nonexistent
    assert meter.pop("nonexistent", "default") == "default"


def test_app_state_values_items_iter():
    """Test AppState values, items and iterator."""
    state = state_module.AppState()
    state[1] = {"total": 100}

    assert len(list(state.values())) >= 1
    assert len(list(state.items())) >= 1
    assert "date" in [k for k in state]


def test_meter_state_initial_values():
    """Test initial values of MeterState."""
    m = state_module.MeterState()
    assert m.total == 0
    assert m.today == 0
    assert m.yesterday == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
