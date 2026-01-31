"""
Tests for state management (state.py).
"""

import datetime

import pytest

import state as state_module

# --- From test_helpers.py ---


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


# --- From test_measurement_logic.py ---


def test_state_update_id_conversion():
    """Test that meter IDs are converted from strings to integers during update."""
    context = state_module.get_context()
    context.state.reset_state()
    sample_data = {"1": {"total": 100, "pulsecount": 10}}
    context.state.update(sample_data)
    assert 1 in context.state.meters
    assert "1" not in context.state.meters
    assert context.state.meters[1].total == 100


def test_state_date_parsing():
    """Test standard date parsing in AppState."""
    state = state_module.AppState()
    sample_data = {"date": "2026-01-20"}
    state.update(sample_data)
    assert isinstance(state.date, datetime.date)
    assert state.date.year == 2026
    assert state.date.day == 20


def test_state_default_initialization():
    """Test default state initialization."""
    state = state_module.AppState()
    assert isinstance(state.date, datetime.date)
    assert state.date == datetime.date.today()
    assert len(state.meters) == 0


def test_state_update_invalid_keys():
    """Test behavior when update data contains non-integer keys."""
    state = state_module.AppState()
    sample_data = {"invalid": {"total": 100}, "2": {"total": 200}}
    state.update(sample_data)
    assert "invalid" not in state.meters
    assert 2 in state.meters
    assert state.meters[2].total == 200


# --- From test_state_missing.py ---


def test_meter_state_iter():
    """Test iterating over MeterState (line 58)."""
    m = state_module.MeterState(name="Test")
    keys = list(m)
    assert "name" in keys
    assert "total" in keys


def test_app_state_setitem_date():
    """Test __setitem__ for date (lines 76-84)."""
    app_state = state_module.AppState()

    # 1. String valid
    app_state["date"] = "2023-01-01"
    assert app_state.date == datetime.date(2023, 1, 1)

    # 2. String invalid (should pass/ignore)
    app_state["date"] = "invalid-date"
    # Should remain unchanged
    assert app_state.date == datetime.date(2023, 1, 1)

    # 3. Date object
    today = datetime.date.today()
    app_state["date"] = today
    assert app_state.date == today


def test_app_state_update_date_exception():
    """Test update with invalid date string (lines 102-103)."""
    app_state = state_module.AppState()
    app_state.update({"date": "bad-date"})
    assert app_state.date == "bad-date"


def test_app_state_update_existing_meter():
    """Test update merging into existing meter (lines 113-115) and legacy (119-120)."""
    app_state = state_module.AppState()
    app_state.meters[1] = state_module.MeterState(total=10)

    # Update existing
    app_state.update({"1": {"total": 20, "name": "Updated"}})
    assert app_state.meters[1].total == 20
    assert app_state.meters[1].name == "Updated"

    # Update with non-dict legacy/weird
    app_state.update({"2": "NotADictOrMeterState"})
    # Should ignore (lines 118-120)
    assert 2 not in app_state.meters


def test_app_state_update_with_meter_state():
    """Test update with MeterState object (line 117)."""
    app_state = state_module.AppState()
    meter = state_module.MeterState(name="DirectObject")

    app_state.update({"3": meter})
    assert 3 in app_state.meters
    assert app_state.meters[3].name == "DirectObject"


def test_app_state_setitem_direct_meter():
    """Test AppState.__setitem__ with direct MeterState object (line 89)."""
    app_state = state_module.AppState()
    meter = state_module.MeterState(total=500, today=50)
    app_state[1] = meter  # Direct assignment, not dict
    assert app_state.meters[1] is meter
    assert app_state.meters[1].total == 500


def test_deprecated_methods():
    """Test deprecated methods for coverage."""
    context = state_module.get_context()
    context.save_measurement()
    context.read_measurement()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
