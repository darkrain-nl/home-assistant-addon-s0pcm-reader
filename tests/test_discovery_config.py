"""
Tests for MQTT discovery configuration variations.
"""

import json
from unittest.mock import MagicMock

import discovery
import state as state_module


def test_send_global_discovery_disabled():
    """Test that global discovery does nothing if disabled in config."""
    context = state_module.get_context()
    context.config = {"mqtt": {"discovery": False}}
    mqttc = MagicMock()

    discovery.send_global_discovery(mqttc)
    mqttc.publish.assert_not_called()


def test_send_meter_discovery_disabled():
    """Test that meter discovery does nothing if disabled in config."""
    context = state_module.get_context()
    context.config = {"mqtt": {"discovery": False}}
    mqttc = MagicMock()

    result = discovery.send_meter_discovery(mqttc, 1, {"name": "test"})
    assert result is None
    mqttc.publish.assert_not_called()


def test_send_meter_discovery_split_topic():
    """Test meter discovery with split_topic enabled."""
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


def test_cleanup_meter_discovery_disabled():
    """Test that cleanup does nothing if discovery is disabled."""
    context = state_module.get_context()
    context.config = {"mqtt": {"discovery": False}}
    mqttc = MagicMock()

    discovery.cleanup_meter_discovery(mqttc, 1)
    mqttc.publish.assert_not_called()
