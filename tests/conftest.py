"""Shared pytest fixtures for S0PCM Reader test suite."""

import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add rootfs source directory to import path.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rootfs", "usr", "src")))

import state as state_module


@pytest.fixture(autouse=True)
def setup_s0pcm_globals():
    """Ensure application context is initialized before test."""
    state_module.get_context()


@pytest.fixture
def mock_serial(mocker):
    """Mock serialx.Serial class for hardware abstraction."""
    return mocker.patch("serialx.Serial")


@pytest.fixture
def mock_aiomqtt_client():
    """Mock aiomqtt.Client for asynchronous MQTT testing."""
    mock = AsyncMock()
    mock.publish = AsyncMock()
    mock.subscribe = AsyncMock()
    mock.unsubscribe = AsyncMock()
    mock.messages = AsyncMock()
    return mock


@pytest.fixture
def temp_config_dir():
    """Provide isolated temporary directory for test configs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_options():
    """Sample configuration dictionary."""
    return {
        "device": "/dev/ttyACM0",
        "log_level": "INFO",
        "mqtt": {
            "host": "core-mosquitto",
            "port": 1883,
            "username": "test_user",
            "password": "test_pass",
            "base_topic": "s0pcmreader",
        },
        "advanced": {"discovery": True, "split_topic": True, "retain": True},
    }


@pytest.fixture
def mock_options_file(temp_config_dir, sample_options):
    """Write sample options.json to temporary test directory."""
    options_path = os.path.join(temp_config_dir, "options.json")
    with open(options_path, "w") as f:
        json.dump(sample_options, f)
    return options_path


@pytest.fixture
def s0pcm_packets():
    """Sample raw serial telegram byte packets."""
    return {
        "header": b"/8237:S0 Pulse Counter V0.6 - 30/30/30/30/30ms\r\n",
        "s0pcm2_data": b"ID:8237:I:10:M1:0:100:M2:0:50\r\n",
        "s0pcm5_data": b"ID:8237:I:10:M1:0:100:M2:0:50:M3:0:25:M4:0:75:M5:0:10\r\n",
        "invalid_length": b"ID:8237:I:10:M1:0:100\r\n",
        "invalid_marker": b"ID:8237:I:10:X1:0:100:M2:0:50\r\n",
        "empty": b"\r\n",
    }


@pytest.fixture
def mock_supervisor_api(mocker):
    """Mock Home Assistant Supervisor HTTP API responses."""

    def mock_urlopen(request):
        """Mock urlopen responses according to target endpoint."""
        mock_response = MagicMock()
        mock_response.status = 200
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "services/mqtt" in url:
            data = {
                "data": {
                    "host": "core-mosquitto",
                    "port": 1883,
                    "username": "mqtt_user",
                    "password": "mqtt_pass",
                }
            }
        elif "states/" in url:
            data = {"state": "1323128", "entity_id": "sensor.s0pcmreader_1_total"}
        elif "states" in url:
            data = [
                {"entity_id": "sensor.s0pcmreader_1_total", "state": "1323128"},
                {"entity_id": "sensor.s0pcmreader_2_total", "state": "5000"},
            ]
        else:
            data = {}
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        return mock_response

    mocker.patch("urllib.request.urlopen", side_effect=mock_urlopen)


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset context state and events before each test run."""
    context = state_module.get_context()
    context.state.reset_state()
    context.lasterror_serial = None
    context.lasterror_mqtt = None
    context.lasterror_share = None
    context.config = None
    context.s0pcm_firmware = "Unknown"
    context.recovery_event = asyncio.Event()
    context.trigger_event = asyncio.Event()
    yield
