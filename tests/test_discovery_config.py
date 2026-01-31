"""
Tests for MQTT discovery configuration variations.
"""

from unittest.mock import MagicMock, patch

import discovery
import state as state_module


def test_send_global_discovery_disabled():
    """Test that global discovery does nothing if disabled in config."""
    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "discovery": False
        }
    }
    mqttc = MagicMock()
    
    discovery.send_global_discovery(mqttc)
    mqttc.publish.assert_not_called()


def test_send_meter_discovery_disabled():
    """Test that meter discovery does nothing if disabled in config."""
    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "discovery": False
        }
    }
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
            "split_topic": True
        }
    }
    mqttc = MagicMock()
    
    discovery.send_meter_discovery(mqttc, 1, {"name": "test"})
    
    # Check that it published a state_topic pointing to the sub-topic
    # Find the 'total' config message
    total_config_call = [call for call in mqttc.publish.call_args_list if "total" in call.args[0] and "{" in str(call.args[1])]
    assert len(total_config_call) > 0
    import json
    payload = json.loads(total_config_call[0].args[1])
    assert payload["state_topic"] == "s0pcm/test/total"


def test_cleanup_meter_discovery_disabled():
    """Test that cleanup does nothing if discovery is disabled."""
    context = state_module.get_context()
    context.config = {
        "mqtt": {
            "discovery": False
        }
    }
    mqttc = MagicMock()
    
    discovery.cleanup_meter_discovery(mqttc, 1)
    mqttc.publish.assert_not_called()
