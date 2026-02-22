"""
Tests for discovery module (discovery.py).
"""

import json
from unittest.mock import MagicMock, patch

# import discovery - lazy imported in tests
import state as state_module


def test_send_global_discovery(mocker):
    """Test global discovery message publishing."""
    import discovery

    mock_mqttc = MagicMock()
    context = state_module.get_context()
    context.config["mqtt"] = {
        "discovery": True,
        "base_topic": "s0pcm",
        "discovery_prefix": "homeassistant",
        "online": "online",
        "offline": "offline",
    }
    context.s0pcm_reader_version = "3.0.0"

    discovery.send_global_discovery(mock_mqttc)

    # Core check: Was something published?
    assert mock_mqttc.publish.called

    # Check status topic
    status_call = [
        c for c in mock_mqttc.publish.call_args_list if "binary_sensor/s0pcm/s0pcm_s0pcm_status/config" in str(c)
    ]
    assert status_call
    payload = json.loads(status_call[0][0][1])
    assert payload["name"] == "S0PCM Reader Status"
    assert payload["device"]["sw_version"] == "3.0.0"


def test_send_meter_discovery(mocker):
    """Test meter discovery message publishing."""
    import discovery

    mock_mqttc = MagicMock()
    context = state_module.get_context()
    context.config["mqtt"] = {
        "discovery": True,
        "base_topic": "s0pcm",
        "discovery_prefix": "homeassistant",
        "split_topic": True,
    }

    meter_data = {"name": "Water"}
    instancename = discovery.send_meter_discovery(mock_mqttc, 1, meter_data)

    assert instancename == "Water"

    # Check total sensor discovery
    total_call = [c for c in mock_mqttc.publish.call_args_list if "sensor/s0pcm/s0pcm_s0pcm_1_total/config" in str(c)]
    assert total_call
    payload = json.loads(total_call[-1][0][1])  # Get last call for this topic
    assert payload["name"] == "Water Total"
    assert payload["state_class"] == "total_increasing"


def test_discovery_disabled(mocker):
    """Test behavior when discovery is disabled."""
    import discovery

    mock_mqttc = MagicMock()
    context = state_module.get_context()
    context.config["mqtt"] = {"discovery": False}

    discovery.send_global_discovery(mock_mqttc)
    assert not mock_mqttc.publish.called

    result = discovery.send_meter_discovery(mock_mqttc, 1, {})
    assert result is None
    assert not mock_mqttc.publish.called


def test_send_global_discovery_with_units(mocker):
    """Test send_global_discovery with custom diagnostics including units (line 93)."""
    import discovery

    context = state_module.get_context()
    context.s0pcm_reader_version = "3.0.0"
    context.config = {
        "mqtt": {
            "discovery": True,
            "base_topic": "s0pcm",
            "discovery_prefix": "homeassistant",
            "online": "online",
            "offline": "offline",
        }
    }
    mqttc = MagicMock()

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
        discovery.send_global_discovery(mqttc)

    # Verify the published config
    # topic: homeassistant/sensor/s0pcm/s0pcm_s0pcm_temp/config
    # find the call
    config_call = next(c for c in mqttc.publish.call_args_list if "temp" in c.args[0])
    payload = json.loads(config_call.args[1])

    assert payload["unit_of_measurement"] == "°C"
    assert payload["device_class"] == "temperature"
    assert payload["name"] == "S0PCM Reader Temperature"


def test_send_meter_discovery_split_topic():
    """Test meter discovery with split_topic enabled."""
    import discovery

    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "discovery": True,
            "base_topic": "s0pcm",
            "discovery_prefix": "homeassistant",
            "split_topic": True,
        }
    }
    mqttc = MagicMock()

    discovery.send_meter_discovery(mqttc, 1, {"name": "test"})

    # Find the 'total' config message
    total_call = next(c for c in mqttc.publish.call_args_list if "total" in c.args[0] and "{" in str(c.args[1]))

    payload = json.loads(total_call.args[1])
    assert payload["state_topic"] == "s0pcm/test/total"


def test_cleanup_meter_discovery_enabled():
    """Test cleanup_meter_discovery with discovery enabled (lines 199-217)."""
    import discovery

    context = state_module.get_context()
    context.config = {"mqtt": {"discovery": True, "base_topic": "s0pcmreader", "discovery_prefix": "homeassistant"}}
    mqttc = MagicMock()

    discovery.cleanup_meter_discovery(mqttc, 5)

    # Should publish empty payloads to clear discovery
    assert mqttc.publish.call_count > 0
    # Check that it published to sensor topics
    topics = [call[0][0] for call in mqttc.publish.call_args_list]
    assert any("sensor" in t for t in topics)
    assert any("text" in t for t in topics)
    assert any("number" in t for t in topics)


def test_cleanup_meter_discovery_disabled():
    """Test that cleanup does nothing if discovery is disabled."""
    import discovery

    context = state_module.get_context()
    context.config = {"mqtt": {"discovery": False}}
    mqttc = MagicMock()

    discovery.cleanup_meter_discovery(mqttc, 1)
    mqttc.publish.assert_not_called()


def test_send_meter_discovery_combined_topic(mocker):
    """Test discovery payload when split_topic is False."""
    import discovery

    context = state_module.get_context()
    context.config["mqtt"] = {
        "discovery": True,
        "base_topic": "s0pcm",
        "discovery_prefix": "homeassistant",
        "split_topic": False,
    }
    mock_mqtt = MagicMock()

    discovery.send_meter_discovery(mock_mqtt, 1, {"name": "Combined"})

    # Check if value_template is correctly set in one of the publish calls
    found_template = False
    for call in mock_mqtt.publish.call_args_list:
        payload_str = call.args[1]
        if payload_str:
            payload = json.loads(payload_str)
            if "value_template" in payload and "{{ value_json.total }}" in payload["value_template"]:
                found_template = True
                break
    assert found_template is True


def test_send_meter_discovery_sanitizes_name():
    """Test that MQTT special characters in meter names are stripped from topics."""
    import discovery

    context = state_module.get_context()
    context.config["mqtt"] = {
        "discovery": True,
        "base_topic": "s0pcm",
        "discovery_prefix": "homeassistant",
        "split_topic": True,
    }
    mqttc = MagicMock()

    meter_data = {"name": "My/Water+Meter#1"}
    instancename = discovery.send_meter_discovery(mqttc, 1, meter_data)

    assert instancename == "MyWaterMeter1"

    # Verify no topics contain MQTT special characters from the name
    for call in mqttc.publish.call_args_list:
        topic = call.args[0]
        if "MyWaterMeter1" in topic:
            assert "/" not in topic.split("s0pcm/")[-1].replace("MyWaterMeter1/", "MyWaterMeter1")
