# Testing Guide for S0PCM Reader

This guide explains how to test the S0PCM Reader application, including mocking serial and MQTT connections.

## Overview

Testing this application requires mocking external dependencies:
- **Serial Port**: Mock the `serial.Serial` class
- **MQTT Broker**: Mock the `paho.mqtt.client.Client` class
- **File System**: Mock file operations for configuration and measurement data
- **Home Assistant API**: Mock HTTP requests to the Supervisor API

## Testing Framework

We'll use:
- **pytest**: Modern Python testing framework
- **pytest-mock**: Provides the `mocker` fixture for easy mocking
- **unittest.mock**: Python's built-in mocking library

## Installation

```bash
pip install pytest pytest-mock pytest-cov
```

## Test Structure

```
home-assistant-addon-s0pcm-reader/
├── rootfs/
│   └── usr/
│       └── src/
│           └── s0pcm_reader.py
└── tests/
    ├── __init__.py
    ├── conftest.py              # Shared fixtures
    ├── test_serial_reader.py    # Serial port tests
    ├── test_mqtt_client.py      # MQTT tests
    ├── test_config.py           # Configuration tests
    ├── test_measurement.py      # Measurement data tests
    └── test_integration.py      # Integration tests
```

## Key Testing Patterns

### 1. Mocking Serial Port

The serial port can be mocked using `unittest.mock.MagicMock`:

```python
from unittest.mock import MagicMock, patch

def test_serial_reading(mocker):
    # Mock the serial.Serial class
    mock_serial = MagicMock()
    mock_serial.readline.return_value = b'ID:8237:I:10:M1:0:100:M2:0:50\r\n'
    
    mocker.patch('serial.Serial', return_value=mock_serial)
    
    # Your test code here
```

### 2. Mocking MQTT Client

The MQTT client can be mocked similarly:

```python
def test_mqtt_publish(mocker):
    # Mock the MQTT client
    mock_mqtt = MagicMock()
    mocker.patch('paho.mqtt.client.Client', return_value=mock_mqtt)
    
    # Simulate successful connection
    mock_mqtt.connect.return_value = 0
    
    # Your test code here
```

### 3. Testing Threading

For testing threaded code, you can:
- Use `threading.Event` to synchronize test execution
- Mock the threading components
- Use timeouts to prevent hanging tests

```python
import threading
import time

def test_threaded_operation():
    stopper = threading.Event()
    trigger = threading.Event()
    
    # Start thread
    thread = MyThread(trigger, stopper)
    thread.start()
    
    # Wait for operation
    trigger.wait(timeout=5)
    
    # Stop thread
    stopper.set()
    thread.join(timeout=5)
    
    assert not thread.is_alive()
```

## Common Test Scenarios

### Serial Port Tests
- Reading valid S0PCM-2 telegrams
- Reading valid S0PCM-5 telegrams
- Handling header packets
- Handling malformed packets
- Connection failures and retries
- Serial port timeout handling

### MQTT Tests
- Successful connection
- Connection failures and retries
- Publishing measurements
- Subscribing to set commands
- MQTT discovery payloads
- State recovery from retained messages
- TLS connection handling

### Configuration Tests
- Loading Home Assistant options
- Default value handling
- Invalid configuration handling
- Service discovery

### Measurement Tests
- Pulse counting logic
- Day change detection
- Total/today/yesterday calculations
- Pulsecount reset handling
- JSON serialization/deserialization

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=rootfs/usr/src --cov-report=html

# Run specific test file
pytest tests/test_serial_reader.py

# Run specific test
pytest tests/test_serial_reader.py::test_parse_s0pcm5_packet

# Run with verbose output
pytest -v

# Run with print statements visible
pytest -s
```

## Best Practices

1. **Isolate Tests**: Each test should be independent
2. **Use Fixtures**: Share common setup code via pytest fixtures
3. **Mock External Dependencies**: Never rely on actual serial ports or MQTT brokers
4. **Test Edge Cases**: Invalid data, connection failures, timeouts
5. **Keep Tests Fast**: Use mocks to avoid real I/O operations
6. **Test One Thing**: Each test should verify a single behavior
7. **Use Descriptive Names**: Test names should describe what they test
8. **Clean Up**: Ensure threads are stopped and resources are released

## Example Test Execution

```bash
# Example output
$ pytest -v
======================== test session starts =========================
collected XX items

tests/test_config.py::test_read_config_defaults PASSED
tests/test_config.py::test_read_config_from_options PASSED
tests/test_serial_reader.py::test_parse_s0pcm2_packet PASSED
tests/test_serial_reader.py::test_parse_s0pcm5_packet PASSED
tests/test_serial_reader.py::test_handle_header PASSED
tests/test_mqtt_client.py::test_mqtt_connect PASSED
tests/test_mqtt_client.py::test_mqtt_publish PASSED
...

===================== XX passed in X.XXs =========================
```

## Continuous Integration

You can integrate these tests into CI/CD pipelines:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.14'
      - run: pip install -r requirements-test.txt
      - run: pytest --cov --cov-report=xml
      - uses: codecov/codecov-action@v2
```

## Next Steps

1. Review the example tests in the `tests/` directory
2. Run the tests to ensure they pass
3. Add new tests as you refactor code
4. Aim for >80% code coverage
5. Use tests to catch regressions during refactoring
