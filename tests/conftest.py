"""
Shared pytest fixtures for S0PCM Reader tests.
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch
import threading
import tempfile
import json
import datetime
# Add the source directory to the path so we can import s0pcm_reader
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'rootfs', 'usr', 'src')))

import s0pcm_reader
import state as state_module
import config as config_module

@pytest.fixture(autouse=True)
def setup_s0pcm_globals():
    """Ensure global variables expected by s0pcm_reader are initialized."""
    # Register trigger with state module (simulating main)
    if not hasattr(s0pcm_reader, 'trigger'):
        s0pcm_reader.trigger = threading.Event()
    
    state_module.register_trigger(s0pcm_reader.trigger)
    
    # Ensure config and measurement exist (they should, but safety first)
    if not hasattr(s0pcm_reader, 'config'):
        s0pcm_reader.config = {}
        
    if not hasattr(s0pcm_reader, 'measurement'):
        import datetime
        s0pcm_reader.measurement = {'date': datetime.date.today()}


@pytest.fixture
def mock_serial(mocker):
    """Mock serial.Serial class."""
    return mocker.patch('serial.Serial')


@pytest.fixture
def mock_mqtt_client(mocker):
    """Mock paho.mqtt.client.Client class."""
    mock = MagicMock()
    mocker.patch('paho.mqtt.client.Client', return_value=mock)
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
        "mqtt_retain": True
    }


@pytest.fixture
def sample_measurement():
    """Sample measurement data."""
    return {
        "date": "2026-01-24",
        1: {
            "name": "Water",
            "pulsecount": 100,
            "total": 1323128,
            "today": 150,
            "yesterday": 200
        },
        2: {
            "pulsecount": 50,
            "total": 5000,
            "today": 25,
            "yesterday": 30
        }
    }


@pytest.fixture
def mock_options_file(temp_config_dir, sample_options):
    """Create a mock options.json file."""
    options_path = os.path.join(temp_config_dir, 'options.json')
    with open(options_path, 'w') as f:
        json.dump(sample_options, f)
    return options_path


@pytest.fixture
def mock_measurement_file(temp_config_dir, sample_measurement):
    """Create a mock measurement.json file."""
    measurement_path = os.path.join(temp_config_dir, 'measurement.json')
    with open(measurement_path, 'w') as f:
        json.dump(sample_measurement, f)
    return measurement_path


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
        "empty": b"\r\n"
    }


@pytest.fixture
def mock_supervisor_api(mocker):
    """Mock Home Assistant Supervisor API."""
    def mock_urlopen(request):
        """Mock urllib.request.urlopen."""
        mock_response = MagicMock()
        mock_response.status = 200
        
        # Determine response based on URL
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        
        if 'services/mqtt' in url:
            # MQTT service discovery
            data = {
                "data": {
                    "host": "core-mosquitto",
                    "port": 1883,
                    "username": "mqtt_user",
                    "password": "mqtt_pass"
                }
            }
        elif 'states/' in url:
            # Single entity state
            data = {
                "state": "1323128",
                "entity_id": "sensor.s0pcmreader_1_total"
            }
        elif 'states' in url:
            # All states
            data = [
                {
                    "entity_id": "sensor.s0pcmreader_1_total",
                    "state": "1323128"
                },
                {
                    "entity_id": "sensor.s0pcmreader_2_total",
                    "state": "5000"
                }
            ]
        else:
            data = {}
        
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        
        return mock_response
    
    mocker.patch('urllib.request.urlopen', side_effect=mock_urlopen)


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global state before each test."""
    # Clear state variables
    state_module.config.clear()
    state_module.measurement.clear()
    state_module.measurement['date'] = datetime.date.today()
    state_module.measurementshare = {}
    state_module.lasterror_serial = None
    state_module.lasterror_mqtt = None
    state_module.lasterrorshare = None
    state_module.s0pcm_firmware = "Unknown"
    
    # Reset config defaults if needed
    config_module.configdirectory = './'
    config_module.measurementname = config_module.configdirectory + 'measurement.json'
    
    yield
