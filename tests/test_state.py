"""
Tests for state management (state.py).
"""

import datetime

import pytest

import state as state_module


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


def test_app_state_reset():
    """Test AppState reset_state method."""
    app_state = state_module.AppState()
    app_state.meters[1] = state_module.MeterState(total=1000)
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


def test_app_state_metadata():
    """Test AppState metadata."""
    context = state_module.AppContext()
    assert context.startup_time is not None


def test_app_state_iter():
    """Test AppState iterator."""
    state = state_module.AppState()
    state.meters[1] = state_module.MeterState(total=100)

    assert 1 in state.meters
    assert "date" in state.model_fields


def test_meter_state_initial_values():
    """Test initial values of MeterState."""
    m = state_module.MeterState()
    assert m.total == 0
    assert m.today == 0
    assert m.yesterday == 0


def test_state_id_lookup():
    """Test meter ID lookup in AppState."""
    context = state_module.AppContext()
    context.state.reset_state()
    context.state.meters[1] = state_module.MeterState(total=100, pulsecount=10)
    assert 1 in context.state.meters
    assert context.state.meters[1].total == 100


def test_state_date_update():
    """Test date update in AppState."""
    state = state_module.AppState()
    state.date = datetime.date.fromisoformat("2026-01-20")
    assert isinstance(state.date, datetime.date)
    assert state.date.year == 2026
    assert state.date.day == 20


def test_state_default_initialization():
    """Test default state initialization."""
    state = state_module.AppState()
    assert isinstance(state.date, datetime.date)
    assert state.date == datetime.date.today()
    assert len(state.meters) == 0


def test_state_meter_assignment():
    """Test behavior when assigning meters."""
    state = state_module.AppState()
    state.meters[2] = state_module.MeterState(total=200)
    assert 2 in state.meters
    assert state.meters[2].total == 200


def test_meter_state_dump():
    """Test dumping MeterState to dict."""
    m = state_module.MeterState(name="Test")
    data = m.model_dump()
    assert data["name"] == "Test"
    assert "total" in data


def test_app_state_date_string():
    """Test date string conversion."""
    app_state = state_module.AppState()
    app_state.date = datetime.date.fromisoformat("2023-01-01")
    assert str(app_state.date) == "2023-01-01"


def test_app_state_meter_update():
    """Test update merging into existing meter."""
    app_state = state_module.AppState()
    app_state.meters[1] = state_module.MeterState(total=10)
    app_state.meters[1].total = 20
    app_state.meters[1].name = "Updated"
    assert app_state.meters[1].total == 20
    assert app_state.meters[1].name == "Updated"


def test_app_state_direct_meter():
    """Test AppState with direct MeterState object."""
    app_state = state_module.AppState()
    meter = state_module.MeterState(total=500, today=50)
    app_state.meters[1] = meter
    assert app_state.meters[1] is meter
    assert app_state.meters[1].total == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
