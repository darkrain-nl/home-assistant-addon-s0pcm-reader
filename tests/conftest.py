"""
Shared pytest fixtures for S0PCM Reader tests.
"""

import json
import os
import sys
import tempfile
import threading
from unittest.mock import MagicMock

import pytest

# Add the source directory to the path so we can import s0pcm_reader
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rootfs", "usr", "src")))

import config as config_module
import s0pcm_reader
import state as state_module


@pytest.fixture(autouse=True)
def setup_s0pcm_globals():
    """Ensure global variables expected by s0pcm_reader are initialized."""
    # Use the real context from state_module
    context = state_module.get_context()
    # Register trigger with context
    trigger = threading.Event()
    context.register_trigger(trigger)
    # Expose trigger on s0pcm_reader module if main tests expect it
    s0pcm_reader.trigger = trigger


@pytest.fixture
def mock_serial(mocker):
    """Mock serial.Serial class."""
    return mocker.patch("serial.Serial")


@pytest.fixture
def mock_mqtt_client(mocker):
    """Mock paho.mqtt.client.Client class."""
    mock = MagicMock()
    mocker.patch("paho.mqtt.client.Client", return_value=mock)
    return mock


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for configuration files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_options():
    """Sample Home Assistant options.json content."""
    return {
        "device": "/dev/ttyACM0",
        "log_level": "INFO",
        "mqtt_host": "core-mosquitto",
        "mqtt_port": 1883,
        "mqtt_username": "test_user",
        "mqtt_password": "test_pass",
        "mqtt_base_topic": "s0pcmreader",
        "mqtt_discovery": True,
        "mqtt_split_topic": True,
        "mqtt_retain": True,
    }


@pytest.fixture
def mock_options_file(temp_config_dir, sample_options):
    """Create a mock options.json file."""
    options_path = os.path.join(temp_config_dir, "options.json")
    with open(options_path, "w") as f:
        json.dump(sample_options, f)
    return options_path


@pytest.fixture
def threading_helpers():
    """Helper utilities for testing threaded code."""

    class ThreadingHelpers:
        @staticmethod
        def create_events():
            """Create trigger and stopper events."""
            return threading.Event(), threading.Event()

        @staticmethod
        def wait_for_thread(thread, timeout=5):
            """Wait for a thread to finish with timeout."""
            thread.join(timeout=timeout)
            return not thread.is_alive()

        @staticmethod
        def stop_thread(thread, stopper, trigger, timeout=5):
            """Stop a thread gracefully."""
            stopper.set()
            trigger.set()
            thread.join(timeout=timeout)
            return not thread.is_alive()

    return ThreadingHelpers()


@pytest.fixture
def s0pcm_packets():
    """Sample S0PCM telegram packets."""
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
    """Mock Home Assistant Supervisor API."""

    def mock_urlopen(request):
        """Mock urllib.request.urlopen."""
        mock_response = MagicMock()
        mock_response.status = 200
        # Determine response based on URL
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "services/mqtt" in url:
            # MQTT service discovery
            data = {"data": {"host": "core-mosquitto", "port": 1883, "username": "mqtt_user", "password": "mqtt_pass"}}
        elif "states/" in url:
            # Single entity state
            data = {"state": "1323128", "entity_id": "sensor.s0pcmreader_1_total"}
        elif "states" in url:
            # All states
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
    """Reset global state before each test."""
    context = state_module.get_context()
    # Use context methods to clear state
    with context.lock:
        context.state.reset_state()
        context.state_share.reset_state()
    context.lasterror_serial = None
    context.lasterror_mqtt = None
    context.lasterror_share = None
    context.s0pcm_firmware = "Unknown"
    # Reset config defaults if needed
    config_module.configdirectory = "./"
    yield
