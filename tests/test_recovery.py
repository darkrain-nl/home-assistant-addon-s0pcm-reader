"""
Comprehensive tests for the recovery module.

Tests cover:
- MQTT message parsing (discovery topics, data topics, date handling)
- HA API methods (fetch_ha_state, fetch_all_ha_states)
- Robust state cleaning logic (units, decimal separators, localization)
- Name-to-ID mapping
- Complete recovery flow and edge cases
"""

import datetime
import json
from unittest.mock import MagicMock

import pytest

from recovery import StateRecoverer
import state as state_module


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client."""
    client = MagicMock()
    client.subscribe = MagicMock()
    client.unsubscribe = MagicMock()
    return client


@pytest.fixture
def recoverer(mock_mqtt_client):
    """Create a StateRecoverer instance with mocked MQTT client."""
    context = state_module.get_context()
    context.config = {"mqtt": {"base_topic": "s0pcmreader", "discovery_prefix": "homeassistant"}}
    return StateRecoverer(mock_mqtt_client)


class TestMQTTMessageParsing:
    """Test MQTT message parsing during recovery."""

    def test_parse_discovery_topic_with_name(self, recoverer):
        """Test parsing discovery config messages to extract meter names."""
        msg = MagicMock()
        msg.topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_1_total/config"
        msg.payload = json.dumps(
            {"unique_id": "s0pcm_s0pcmreader_1_total", "state_topic": "s0pcmreader/Water/total"}
        ).encode()

        recoverer.on_message(None, None, msg)

        assert 1 in recoverer.recovered_names
        assert recoverer.recovered_names[1] == "Water"

    def test_parse_discovery_topic_ignores_id_as_name(self, recoverer):
        """Test that numeric IDs are not stored as names."""
        msg = MagicMock()
        msg.topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_2_total/config"
        msg.payload = json.dumps(
            {"unique_id": "s0pcm_s0pcmreader_2_total", "state_topic": "s0pcmreader/2/total"}
        ).encode()

        recoverer.on_message(None, None, msg)

        assert 2 not in recoverer.recovered_names

    def test_parse_discovery_topic_ignores_none(self, recoverer):
        """Test that 'None' is not stored as a valid name."""
        msg = MagicMock()
        msg.topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_3_total/config"
        msg.payload = json.dumps(
            {"unique_id": "s0pcm_s0pcmreader_3_total", "state_topic": "s0pcmreader/None/total"}
        ).encode()

        recoverer.on_message(None, None, msg)

        assert 3 not in recoverer.recovered_names

    def test_parse_data_topic_total(self, recoverer):
        """Test parsing total value from MQTT data topic."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/1/total"
        msg.payload = b"1234567"

        recoverer.on_message(None, None, msg)

        assert "1" in recoverer.recovered_data
        assert recoverer.recovered_data["1"]["total"] == 1234567

    def test_parse_data_topic_today(self, recoverer):
        """Test parsing today value from MQTT data topic."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/Water/today"
        msg.payload = b"150"

        recoverer.on_message(None, None, msg)

        assert "Water" in recoverer.recovered_data
        assert recoverer.recovered_data["Water"]["today"] == 150

    def test_parse_data_topic_yesterday(self, recoverer):
        """Test parsing yesterday value from MQTT data topic."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/2/yesterday"
        msg.payload = b"200"

        recoverer.on_message(None, None, msg)

        assert "2" in recoverer.recovered_data
        assert recoverer.recovered_data["2"]["yesterday"] == 200

    def test_parse_data_topic_pulsecount(self, recoverer):
        """Test parsing pulsecount value from MQTT data topic."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/1/pulsecount"
        msg.payload = b"42"

        recoverer.on_message(None, None, msg)

        assert "1" in recoverer.recovered_data
        assert recoverer.recovered_data["1"]["pulsecount"] == 42

    def test_parse_date_topic(self, recoverer):
        """Test parsing date from MQTT topic."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/date"
        msg.payload = b"2026-01-25"

        recoverer.on_message(None, None, msg)

        assert recoverer.context.state.date == datetime.date(2026, 1, 25)

    def test_parse_invalid_json_gracefully(self, recoverer):
        """Test that invalid JSON in discovery topics doesn't crash."""
        msg = MagicMock()
        msg.topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_1_total/config"
        msg.payload = b"{invalid json"

        # Should not raise exception
        recoverer.on_message(None, None, msg)

        assert 1 not in recoverer.recovered_names

    def test_parse_invalid_number_gracefully(self, recoverer):
        """Test that invalid numbers in data topics are ignored."""
        msg = MagicMock()
        msg.topic = "s0pcmreader/1/total"
        msg.payload = b"not_a_number"

        # Should not raise exception
        recoverer.on_message(None, None, msg)

        assert "1" not in recoverer.recovered_data


class TestHAAPIFallback:
    """Test Home Assistant API fallback methods."""

    def test_fetch_ha_state_success(self, recoverer, mocker):
        """Test successful HA API state fetch."""
        mocker.patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test_token"})

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            {"state": "1234567", "entity_id": "sensor.s0pcmreader_1_total"}
        ).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        mocker.patch("urllib.request.urlopen", return_value=mock_response)

        result = recoverer.fetch_ha_state("sensor.s0pcmreader_1_total")

        assert result == "1234567"

    def test_fetch_ha_state_no_token(self, recoverer, mocker):
        """Test HA API fetch returns None when no token available."""
        mocker.patch.dict("os.environ", {}, clear=True)

        result = recoverer.fetch_ha_state("sensor.s0pcmreader_1_total")

        assert result is None

    def test_fetch_ha_state_unknown_state(self, recoverer, mocker):
        """Test HA API fetch returns None for unknown/unavailable states."""
        mocker.patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test_token"})
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            {"state": "unknown", "entity_id": "sensor.s0pcmreader_1_total"}
        ).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mocker.patch("urllib.request.urlopen", return_value=mock_response)

        result = recoverer.fetch_ha_state("sensor.s0pcmreader_1_total")

        assert result is None

    def test_fetch_all_ha_states_success(self, recoverer, mocker):
        """Test successful fetch of all HA states."""
        mocker.patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test_token"})

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            [
                {"entity_id": "sensor.s0pcmreader_1_total", "state": "1234567"},
                {"entity_id": "sensor.s0pcmreader_2_total", "state": "5000"},
            ]
        ).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        mocker.patch("urllib.request.urlopen", return_value=mock_response)

        result = recoverer.fetch_all_ha_states()

        assert len(result) == 2
        assert result[0]["entity_id"] == "sensor.s0pcmreader_1_total"
        assert result[1]["state"] == "5000"

    def test_fetch_all_ha_states_no_token(self, recoverer, mocker):
        """Test fetch all states returns empty list when no token."""
        mocker.patch.dict("os.environ", {}, clear=True)

        result = recoverer.fetch_all_ha_states()

        assert result == []


class TestRobustStateCleaning:
    """Test the robust state string cleaning logic."""

    def test_clean_state_with_cubic_meters(self, recoverer):
        """Test cleaning state with m³ unit."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState(name="Water")

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1234.56 m³"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234

    def test_clean_state_with_kwh(self, recoverer):
        """Test cleaning state with kWh unit."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "5678.90 kWh"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 5678

    def test_clean_state_with_comma_decimal(self, recoverer):
        """Test cleaning state with European decimal separator (comma)."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1234,56"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234

    def test_clean_state_with_thousands_separator(self, recoverer):
        """Test cleaning state with thousands separators."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.234.567"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234567

    def test_clean_state_with_mixed_separators(self, recoverer):
        """Test cleaning state with both dot and comma (European format)."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.234,56 m³"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        # European format with mixed separators: all separators removed -> 123456
        assert result == 123456

    def test_clean_state_plain_number(self, recoverer):
        """Test cleaning plain numeric state."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "9876543"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 9876543

    def test_find_total_with_name_pattern(self, recoverer):
        """Test finding total using name-based entity pattern."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState(name="Water Meter")

        ha_states = [{"entity_id": "sensor.s0pcmreader_water_meter_total", "state": "12345"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 12345

    def test_find_total_returns_none_for_unavailable(self, recoverer):
        """Test that unavailable states return None."""
        recoverer.context.config["mqtt"]["base_topic"] = "s0pcmreader"
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "unavailable"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result is None


class TestRecoveryFlow:
    """Test the complete recovery flow."""

    def test_run_subscribes_to_topics(self, recoverer, mocker):
        """Test that run() subscribes to all necessary topics."""
        mocker.patch("time.sleep")

        recoverer.run()

        # Verify subscriptions
        assert recoverer.mqttc.subscribe.call_count == 6
        topics = [c[0][0] for c in recoverer.mqttc.subscribe.call_args_list]
        assert "s0pcmreader/+/total" in topics
        assert "s0pcmreader/+/today" in topics
        assert "s0pcmreader/+/yesterday" in topics
        assert "s0pcmreader/+/pulsecount" in topics
        assert "s0pcmreader/date" in topics
        assert "homeassistant/sensor/s0pcmreader/#" in topics

    def test_run_unsubscribes_after_recovery(self, recoverer, mocker):
        """Test that run() unsubscribes from topics after recovery."""
        mocker.patch("time.sleep")

        recoverer.run()

        # Verify unsubscriptions
        assert recoverer.mqttc.unsubscribe.call_count == 6

    def test_run_restores_original_on_message(self, recoverer, mocker):
        """Test that run() restores the original on_message handler."""
        mocker.patch("time.sleep")
        original_handler = MagicMock()
        recoverer.mqttc.on_message = original_handler

        recoverer.run()

        assert recoverer.mqttc.on_message == original_handler

    def test_run_initializes_meters_from_mqtt_data(self, recoverer, mocker):
        """Test that run() initializes meters from recovered MQTT data."""
        mocker.patch("time.sleep")

        # Simulate recovered data
        recoverer.recovered_data = {"1": {"total": 1000, "today": 50, "yesterday": 40, "pulsecount": 10}}
        recoverer.recovered_names = {1: "Water"}

        recoverer.run()

        assert 1 in recoverer.context.state.meters
        meter = recoverer.context.state.meters[1]
        assert meter.name == "Water"
        assert meter.total == 1000
        assert meter.today == 50
        assert meter.yesterday == 40
        assert meter.pulsecount == 10

    def test_run_skips_zero_only_data(self, recoverer, mocker):
        """Test that run() doesn't initialize meters with only zero values."""
        mocker.patch("time.sleep")

        # Simulate recovered data with all zeros
        recoverer.recovered_data = {"1": {"total": 0, "today": 0, "yesterday": 0, "pulsecount": 0}}

        recoverer.run()

        assert 1 not in recoverer.context.state.meters

    def test_run_uses_ha_api_fallback(self, recoverer, mocker):
        """Test that run() uses HA API fallback for missing totals."""
        mocker.patch("time.sleep")
        mocker.patch.object(
            recoverer,
            "fetch_all_ha_states",
            return_value=[{"entity_id": "sensor.s0pcmreader_1_total", "state": "5000"}],
        )

        # Initialize meter with zero total
        recoverer.context.state.meters[1] = state_module.MeterState()

        recoverer.run()

        assert recoverer.context.state.meters[1].total == 5000

    def test_run_merges_name_and_id_data(self, recoverer, mocker):
        """Test that run() merges data from both ID and name topics."""
        mocker.patch("time.sleep")

        # Simulate data under both ID and name
        recoverer.recovered_data = {"1": {"total": 1000, "pulsecount": 10}, "Water": {"today": 50, "yesterday": 40}}
        recoverer.recovered_names = {1: "Water"}

        recoverer.run()

        meter = recoverer.context.state.meters[1]
        assert meter.name == "Water"
        assert meter.total == 1000
        assert meter.today == 50
        assert meter.yesterday == 40
        assert meter.pulsecount == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
