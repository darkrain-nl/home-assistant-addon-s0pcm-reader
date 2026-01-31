"""
Tests for measurement data processing logic within the AppState and AppContext models.
"""
import pytest
import datetime
import state as state_module


def test_state_update_id_conversion():
    """Test that meter IDs are converted from strings to integers during update."""
    context = state_module.get_context()
    context.state.reset_state()

    # Update data: { "1": { ... } } should become { 1: { ... } }
    sample_data = {
        "1": {"total": 100, "pulsecount": 10}
    }

    context.state.update(sample_data)

    # Meter 1 should be an integer key now
    assert 1 in context.state.meters
    assert "1" not in context.state.meters
    assert context.state.meters[1].total == 100


def test_state_date_parsing():
    """Test standard date parsing in AppState."""
    state = state_module.AppState()

    # 1. Standard string date
    sample_data = {"date": "2026-01-20"}
    state.update(sample_data)

    assert isinstance(state.date, datetime.date)
    assert state.date.year == 2026
    assert state.date.day == 20


def test_state_default_initialization():
    """Test default state initialization."""
    state = state_module.AppState()

    # Should default to today's date and empty meters
    assert isinstance(state.date, datetime.date)
    assert state.date == datetime.date.today()
    assert len(state.meters) == 0


def test_state_update_invalid_keys():
    """Test behavior when update data contains non-integer keys."""
    state = state_module.AppState()

    sample_data = {
        "invalid": {"total": 100},
        "2": {"total": 200}
    }

    state.update(sample_data)

    # "invalid" should be ignored, "2" should be converted to 2
    assert "invalid" not in state.meters
    assert 2 in state.meters
    assert state.meters[2].total == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
