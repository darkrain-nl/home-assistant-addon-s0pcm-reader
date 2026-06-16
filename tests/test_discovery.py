"""
Tests for discovery module (discovery.py).
"""

import json
from unittest.mock import AsyncMock, patch

from helpers import make_test_config

import state as state_module
from state import MeterState


async def test_send_global_discovery_new_ha(mocker):
    """Test global discovery message publishing with HA >= 2025.5.0."""
    import discovery

    mock_client = AsyncMock()
    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm")
    context.s0pcm_reader_version = "3.0.0"

    mocker.patch("utils.get_ha_core_version", new_callable=AsyncMock, return_value="2025.5.0")

    await discovery.send_global_discovery(mock_client, context)

    # Core check: Was something published?
    assert mock_client.publish.called

    # Check status topic
    status_call = [
        c for c in mock_client.publish.call_args_list if "binary_sensor/s0pcm/s0pcm_s0pcm_status/config" in c.args[0]
    ]
    assert status_call
    payload = json.loads(status_call[0].args[1])
    assert payload["name"] == "S0PCM Reader Status"
    assert payload["device"]["sw_version"] == "3.0.0"

    # Check startup_time sensor
    startup_call = [
        c for c in mock_client.publish.call_args_list if "sensor/s0pcm/s0pcm_s0pcm_startup_time/config" in c.args[0]
    ]
    assert startup_call
    startup_payload = json.loads(startup_call[0].args[1])
    assert startup_payload["device_class"] == "uptime"
    assert startup_payload["icon"] == "mdi:clock-start"


async def test_send_global_discovery_old_ha(mocker):
    """Test global discovery message publishing with HA < 2025.5.0."""
    import discovery

    mock_client = AsyncMock()
    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm")
    context.s0pcm_reader_version = "3.0.0"

    mocker.patch("utils.get_ha_core_version", new_callable=AsyncMock, return_value="2024.12.0")

    await discovery.send_global_discovery(mock_client, context)

    # Check startup_time sensor fallback
    startup_call = [
        c for c in mock_client.publish.call_args_list if "sensor/s0pcm/s0pcm_s0pcm_startup_time/config" in c.args[0]
    ]
    assert startup_call
    startup_payload = json.loads(startup_call[0].args[1])
    assert startup_payload["device_class"] == "timestamp"
    assert startup_payload["icon"] == "mdi:clock-outline"


async def test_send_meter_discovery(mocker):
    """Test meter discovery message publishing."""
    import discovery

    mock_client = AsyncMock()
    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm")

    meter_state = MeterState(name="Water")
    instancename = await discovery.send_meter_discovery(mock_client, context, 1, meter_state)

    assert instancename == "Water"

    # Check total sensor discovery
    total_call = [
        c for c in mock_client.publish.call_args_list if "sensor/s0pcm/s0pcm_s0pcm_1_total/config" in c.args[0]
    ]
    assert total_call
    payload = json.loads(total_call[-1].args[1])  # Get last call for this topic
    assert payload["name"] == "Water Total"
    assert payload["state_class"] == "total_increasing"
    assert payload["availability_topic"] == "s0pcm/status"
    assert payload["payload_available"] == "online"
    assert payload["payload_not_available"] == "offline"

    # Verify purge of obsolete diagnostic sensors (PPS and Activity)
    activity_clear = [
        c
        for c in mock_client.publish.call_args_list
        if "binary_sensor/s0pcm/s0pcm_s0pcm_1_activity/config" in c.args[0] and c.args[1] == ""
    ]
    pps_clear = [
        c
        for c in mock_client.publish.call_args_list
        if "sensor/s0pcm/s0pcm_s0pcm_1_pps/config" in c.args[0] and c.args[1] == ""
    ]
    assert activity_clear
    assert pps_clear


async def test_discovery_disabled(mocker):
    """Test behavior when discovery is disabled."""
    import discovery

    mock_client = AsyncMock()
    context = state_module.get_context()
    context.config = make_test_config(discovery=False)

    await discovery.send_global_discovery(mock_client, context)
    assert not mock_client.publish.called

    result = await discovery.send_meter_discovery(mock_client, context, 1, MeterState())
    assert result is None
    assert not mock_client.publish.called


async def test_send_global_discovery_with_units(mocker):
    """Test send_global_discovery with custom diagnostics including units (line 93)."""
    import discovery

    context = state_module.get_context()
    context.s0pcm_reader_version = "3.0.0"
    context.config = make_test_config(base_topic="s0pcm")
    mock_client = AsyncMock()

    # Custom diagnostics with all fields including 'unit'
    custom_diags = [
        {
            "id": "temp",
            "name": "Temperature",
            "icon": "mdi:thermometer",
            "unit": "°C",
            "class": "temperature",
        }
    ]

    with patch("discovery.GLOBAL_DIAGNOSTICS", custom_diags):
        await discovery.send_global_discovery(mock_client, context)

    # Verify the published config
    config_call = next(c for c in mock_client.publish.call_args_list if "temp" in c.args[0])
    payload = json.loads(config_call.args[1])

    assert payload["unit_of_measurement"] == "°C"
    assert payload["device_class"] == "temperature"
    assert payload["name"] == "S0PCM Reader Temperature"


async def test_send_meter_discovery_split_topic():
    """Test meter discovery with split_topic enabled."""
    import discovery

    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm", split_topic=True)
    mock_client = AsyncMock()

    await discovery.send_meter_discovery(mock_client, context, 1, MeterState(name="test"))

    # Find the 'total' config message
    total_call = next(c for c in mock_client.publish.call_args_list if "total" in c.args[0] and "{" in str(c.args[1]))

    payload = json.loads(total_call.args[1])
    assert payload["state_topic"] == "s0pcm/test/total"


async def test_cleanup_meter_discovery_enabled():
    """Test cleanup_meter_discovery with discovery enabled (lines 199-217)."""
    import discovery

    context = state_module.get_context()
    context.config = make_test_config()
    mock_client = AsyncMock()

    await discovery.cleanup_meter_discovery(mock_client, context, 5)

    # Should publish empty payloads to clear discovery
    assert mock_client.publish.call_count > 0
    # Check that it published to sensor topics
    topics = [call[0][0] for call in mock_client.publish.call_args_list]
    assert any("sensor" in t for t in topics)
    assert any("text" in t for t in topics)
    assert any("number" in t for t in topics)
    # Check for diagnostic sensor cleanup
    assert any("binary_sensor" in t and "activity" in t for t in topics)
    assert any("sensor" in t and "pps" in t for t in topics)


async def test_cleanup_meter_discovery_disabled():
    """Test that cleanup does nothing if discovery is disabled."""
    import discovery

    context = state_module.get_context()
    context.config = make_test_config(discovery=False)
    mock_client = AsyncMock()

    await discovery.cleanup_meter_discovery(mock_client, context, 1)
    mock_client.publish.assert_not_called()


async def test_send_meter_discovery_combined_topic(mocker):
    """Test discovery payload when split_topic is False."""
    import discovery

    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm", split_topic=False)
    mock_client = AsyncMock()

    await discovery.send_meter_discovery(mock_client, context, 1, MeterState(name="Combined"))

    # Check if value_template is correctly set in one of the publish calls
    found_template = False
    for call in mock_client.publish.call_args_list:
        payload_str = call.args[1]
        if payload_str:
            payload = json.loads(payload_str)
            if "value_template" in payload and "{{ value_json.total }}" in payload["value_template"]:
                found_template = True
                break
    assert found_template is True


async def test_send_meter_discovery_sanitizes_name():
    """Test that MQTT special characters in meter names are stripped from topics."""
    import discovery

    context = state_module.get_context()
    context.config = make_test_config(base_topic="s0pcm")
    mock_client = AsyncMock()

    meter_state = MeterState(name="My/Water+Meter#1")
    instancename = await discovery.send_meter_discovery(mock_client, context, 1, meter_state)

    assert instancename == "MyWaterMeter1"

    # Verify no topics contain MQTT special characters from the name
    for call in mock_client.publish.call_args_list:
        topic = call.args[0]
        if "MyWaterMeter1" in topic:
            assert "/" not in topic.split("s0pcm/")[-1].replace("MyWaterMeter1/", "MyWaterMeter1")
