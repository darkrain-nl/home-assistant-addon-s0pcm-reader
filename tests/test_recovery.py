"""
Comprehensive tests for the recovery module.

Tests cover:
- Message parsing (discovery topics, data topics, date handling)
- HA API methods (fetch_ha_state, fetch_all_ha_states)
- Robust state cleaning logic (units, decimal separators, localization)
- Name-to-ID mapping
- Complete recovery flow and edge cases
"""

import asyncio
import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from helpers import make_test_config
import pytest

from recovery import StateRecoverer
import state as state_module


@pytest.fixture
def mock_mqtt_client():
    """Create a mock aiomqtt Client."""
    client = AsyncMock()
    client.subscribe = AsyncMock()
    client.unsubscribe = AsyncMock()
    client.messages = AsyncMock()
    return client


@pytest.fixture
def recoverer(mock_mqtt_client):
    """Create a StateRecoverer instance with mocked MQTT client."""
    context = state_module.get_context()
    context.config = make_test_config(recovery_wait=0)
    return StateRecoverer(context, mock_mqtt_client)


class TestMQTTMessageParsing:
    """Test MQTT message parsing during recovery."""

    def test_process_message_discovery_topic_with_name(self, recoverer):
        """Test parsing discovery config messages to extract meter names."""
        topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_1_total/config"
        payload = json.dumps(
            {"unique_id": "s0pcm_s0pcmreader_1_total", "state_topic": "s0pcmreader/Water/total"}
        ).encode()

        recoverer._process_message(topic, payload)

        assert 1 in recoverer.recovered_names
        assert recoverer.recovered_names[1] == "Water"

    def test_process_message_discovery_topic_ignores_id_as_name(self, recoverer):
        """Test that numeric IDs are not stored as names."""
        topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_2_total/config"
        payload = json.dumps({"unique_id": "s0pcm_s0pcmreader_2_total", "state_topic": "s0pcmreader/2/total"}).encode()

        recoverer._process_message(topic, payload)

        assert 2 not in recoverer.recovered_names

    def test_process_message_discovery_topic_ignores_none(self, recoverer):
        """Test that 'None' is not stored as a valid name."""
        topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_3_total/config"
        payload = json.dumps(
            {"unique_id": "s0pcm_s0pcmreader_3_total", "state_topic": "s0pcmreader/None/total"}
        ).encode()

        recoverer._process_message(topic, payload)

        assert 3 not in recoverer.recovered_names

    def test_process_message_data_topic_total(self, recoverer):
        """Test parsing total value from MQTT data topic."""
        recoverer._process_message("s0pcmreader/1/total", b"1234567")

        assert "1" in recoverer.recovered_data
        assert recoverer.recovered_data["1"]["total"] == 1234567

    def test_process_message_data_topic_today(self, recoverer):
        """Test parsing today value from MQTT data topic."""
        recoverer._process_message("s0pcmreader/Water/today", b"150")

        assert "Water" in recoverer.recovered_data
        assert recoverer.recovered_data["Water"]["today"] == 150

    def test_process_message_data_topic_yesterday(self, recoverer):
        """Test parsing yesterday value from MQTT data topic."""
        recoverer._process_message("s0pcmreader/2/yesterday", b"200")

        assert "2" in recoverer.recovered_data
        assert recoverer.recovered_data["2"]["yesterday"] == 200

    def test_process_message_data_topic_pulsecount(self, recoverer):
        """Test parsing pulsecount value from MQTT data topic."""
        recoverer._process_message("s0pcmreader/1/pulsecount", b"42")

        assert "1" in recoverer.recovered_data
        assert recoverer.recovered_data["1"]["pulsecount"] == 42

    def test_process_message_date_topic(self, recoverer):
        """Test parsing date from MQTT topic."""
        recoverer._process_message("s0pcmreader/date", b"2026-01-25")

        assert recoverer.context.state.date == datetime.date(2026, 1, 25)

    def test_process_message_invalid_json_gracefully(self, recoverer):
        """Test that invalid JSON in discovery topics doesn't crash."""
        topic = "homeassistant/sensor/s0pcmreader/s0pcm_s0pcmreader_1_total/config"
        recoverer._process_message(topic, b"{invalid json")

        assert 1 not in recoverer.recovered_names

    def test_process_message_invalid_number_gracefully(self, recoverer):
        """Test that invalid numbers in data topics are ignored."""
        recoverer._process_message("s0pcmreader/1/total", b"not_a_number")

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
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState(name="Water")

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1234.56 m³"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234

    def test_clean_state_with_kwh(self, recoverer):
        """Test cleaning state with kWh unit."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "5678.90 kWh"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 5678

    def test_clean_state_with_comma_decimal(self, recoverer):
        """Test cleaning state with European decimal separator (comma)."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1234,56"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234

    def test_clean_state_with_thousands_separator(self, recoverer):
        """Test cleaning state with thousands separators."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.234.567"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 1234567

    def test_clean_state_with_mixed_separators(self, recoverer):
        """Test cleaning state with both dot and comma (European format)."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.234,56 m³"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        # European format with mixed separators: comma treated as decimal -> 1234
        assert result == 1234

    def test_clean_state_plain_number(self, recoverer):
        """Test cleaning plain numeric state."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "9876543"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 9876543

    def test_find_total_with_name_pattern(self, recoverer):
        """Test finding total using name-based entity pattern."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState(name="Water Meter")

        ha_states = [{"entity_id": "sensor.s0pcmreader_water_meter_total", "state": "12345"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result == 12345

    def test_find_total_returns_none_for_unavailable(self, recoverer):
        """Test that unavailable states return None."""
        recoverer.context.config = make_test_config()
        recoverer.context.state.meters[1] = state_module.MeterState()

        ha_states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "unavailable"}]

        result = recoverer._find_total_in_ha(1, ha_states)

        assert result is None


class TestRecoveryFlow:
    """Test the complete recovery flow."""

    async def test_run_subscribes_to_topics(self, recoverer, mocker):
        """Test that run() subscribes to all necessary topics."""

        # Mock messages to immediately timeout
        async def empty_messages():
            return
            yield  # Make it an async generator that yields nothing

        recoverer.client.messages = empty_messages()

        await recoverer.run()

        # Verify subscriptions
        assert recoverer.client.subscribe.call_count == 6
        topics = [c[0][0] for c in recoverer.client.subscribe.call_args_list]
        assert "s0pcmreader/+/total" in topics
        assert "s0pcmreader/+/today" in topics
        assert "s0pcmreader/+/yesterday" in topics
        assert "s0pcmreader/+/pulsecount" in topics
        assert "s0pcmreader/date" in topics
        assert "homeassistant/sensor/s0pcmreader/#" in topics

    async def test_run_unsubscribes_after_recovery(self, recoverer, mocker):
        """Test that run() unsubscribes from topics after recovery."""

        async def empty_messages():
            return
            yield

        recoverer.client.messages = empty_messages()

        await recoverer.run()

        # Verify unsubscriptions
        assert recoverer.client.unsubscribe.call_count == 6

    async def test_run_receives_retained_messages_and_timeouts(self, recoverer, mocker):
        """Test that run() successfully processes received messages and handles TimeoutError gracefully."""

        # Yield a couple of messages, then wait to trigger TimeoutError
        async def message_generator():
            msg1 = MagicMock()
            msg1.topic = "s0pcmreader/1/total"
            msg1.payload = b"12345"
            yield msg1

            msg2 = MagicMock()
            msg2.topic = "s0pcmreader/Water/name"
            msg2.payload = b"Water"
            yield msg2

            await asyncio.sleep(0.05)  # sleep to let timeout happen

        recoverer.client.messages = message_generator()

        # Set recovery wait to a very small value so timeout is quick
        recoverer.context.config.mqtt.recovery_wait = 0.01

        await recoverer.run()

        # Check that the messages were processed and saved to recovered_data
        assert "1" in recoverer.recovered_data
        assert recoverer.recovered_data["1"]["total"] == 12345

    async def test_run_initializes_meters_from_mqtt_data(self, recoverer, mocker):
        """Test that run() initializes meters from recovered MQTT data."""

        async def empty_messages():
            return
            yield

        recoverer.client.messages = empty_messages()

        # Simulate recovered data
        recoverer.recovered_data = {"1": {"total": 1000, "today": 50, "yesterday": 40, "pulsecount": 10}}
        recoverer.recovered_names = {1: "Water"}

        await recoverer.run()

        assert 1 in recoverer.context.state.meters
        meter = recoverer.context.state.meters[1]
        assert meter.name == "Water"
        assert meter.total == 1000
        assert meter.today == 50
        assert meter.yesterday == 40
        assert meter.pulsecount == 10

    async def test_run_skips_zero_only_data(self, recoverer, mocker):
        """Test that run() doesn't initialize meters with only zero values."""

        async def empty_messages():
            return
            yield

        recoverer.client.messages = empty_messages()

        # Simulate recovered data with all zeros
        recoverer.recovered_data = {"1": {"total": 0, "today": 0, "yesterday": 0, "pulsecount": 0}}

        await recoverer.run()

        assert 1 not in recoverer.context.state.meters

    async def test_run_uses_ha_api_fallback(self, recoverer, mocker):
        """Test that run() uses HA API fallback for missing totals."""

        async def empty_messages():
            return
            yield

        recoverer.client.messages = empty_messages()

        mocker.patch.object(
            recoverer,
            "fetch_all_ha_states",
            return_value=[{"entity_id": "sensor.s0pcmreader_1_total", "state": "5000"}],
        )

        # Initialize meter with zero total
        recoverer.context.state.meters[1] = state_module.MeterState()

        await recoverer.run()

        assert recoverer.context.state.meters[1].total == 5000

        meter = recoverer.context.state.meters[1]
        assert meter.name is None
        assert meter.today == 0
        assert meter.yesterday == 0
        assert meter.pulsecount == 0


class TestRecoveryExceptions:
    def test_fetch_ha_state_exception(self, recoverer):
        """Test fetch_ha_state exception handling."""
        with (
            patch("os.getenv", return_value="TOKEN"),
            patch("urllib.request.urlopen", side_effect=Exception("API Error")),
        ):
            res = recoverer.fetch_ha_state("sensor.test")
            assert res is None

    def test_fetch_all_ha_states_exception(self, recoverer):
        """Test fetch_all_ha_states exception handling."""
        with (
            patch("os.getenv", return_value="TOKEN"),
            patch("urllib.request.urlopen", side_effect=Exception("API Error")),
        ):
            res = recoverer.fetch_all_ha_states()
            assert res == []

    async def test_run_recover_named_meter_gap(self, recoverer):
        """Test recovering a meter by name that isn't in main state yet."""
        recoverer.recovered_names = {10: "Garage"}

        async def empty_messages():
            return
            yield

        recoverer.client.messages = empty_messages()

        await recoverer.run()

        context = state_module.get_context()
        assert 10 in context.state.meters
        assert context.state.meters[10].name == "Garage"

    def test_find_total_chaos_format(self, recoverer):
        """Test _find_total_in_ha with chaos format."""
        states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.1.1,1,1"}]
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState()

        val = recoverer._find_total_in_ha(1, states)
        assert val == 11111

    def test_find_total_empty(self, recoverer):
        """Test _find_total_in_ha with empty string."""
        states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": " "}]
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState()

        val = recoverer._find_total_in_ha(1, states)
        assert val is None

    def test_find_total_value_error(self, recoverer):
        """Test _find_total_in_ha with invalid number."""
        states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "."}]
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState()

        val = recoverer._find_total_in_ha(1, states)
        assert val is None

    def test_process_message_date_error(self, recoverer):
        """Test _process_message date parsing error."""
        recoverer._process_message("s0pcmreader/date", b"invalid-date")
        assert recoverer.context.state.date != "invalid-date"

    def test_find_total_complex_US(self, recoverer):
        """Test _find_total_in_ha with US format 1,000.50."""
        states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1,000.50"}]
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState()

        val = recoverer._find_total_in_ha(1, states)
        assert val == 1000

    def test_find_total_complex_EU(self, recoverer):
        """Test _find_total_in_ha with EU format 1.000,50."""
        states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1.000,50"}]
        context = state_module.get_context()
        context.state.meters[1] = state_module.MeterState()

        val = recoverer._find_total_in_ha(1, states)
        assert val == 1000


async def test_run_name_data_merge(recoverer, mocker):
    """Test name-based data merging with max() logic."""

    async def empty_messages():
        return
        yield

    recoverer.client.messages = empty_messages()

    # Setup: meter with name and data under name topic
    recoverer.recovered_names = {1: "WaterMeter"}
    recoverer.recovered_data = {
        "1": {"total": 100},
        "WaterMeter": {"total": 150, "today": 15, "yesterday": 5, "pulsecount": 20},
    }

    await recoverer.run()

    meter = recoverer.context.state.meters[1]
    assert meter.name == "WaterMeter"
    # Should use max() from both sources
    assert meter.total == 150
    assert meter.today == 15


def test_find_total_many_commas(recoverer):
    """Test number parsing with many commas."""
    states = [{"entity_id": "sensor.s0pcmreader_1_total", "state": "1,000,000"}]
    context = state_module.get_context()
    context.state.meters[1] = state_module.MeterState()

    val = recoverer._find_total_in_ha(1, states)
    assert val == 1000000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
