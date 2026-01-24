# S0PCM Reader Tests

This directory contains the test suite for the S0PCM Reader Home Assistant addon.

## Quick Start

```bash
# Install test dependencies (from the tests directory)
pip install -r tests/requirements-test.txt

# Run all tests (from project root)
pytest tests/

# Run with coverage report
pytest tests/ --cov=rootfs/usr/src --cov-report=html

# Run specific test file
pytest tests/test_serial_reader.py -v

# Run tests matching a pattern
pytest tests/ -k "test_mqtt" -v
```

## Test Structure

```
tests/
├── __init__.py              # Package marker
├── conftest.py              # Shared fixtures and test configuration
├── pytest.ini               # Pytest configuration
├── requirements-test.txt    # Test dependencies
├── TESTING_GUIDE.md         # Comprehensive testing guide
├── README.md                # This file (quick reference)
├── test_config.py           # Configuration loading tests
├── test_serial_reader.py    # Serial port and packet parsing tests
├── test_mqtt_client.py      # MQTT client tests
├── test_loops.py            # Main thread integration tests
└── test_main.py             # Startup and signal handling tests
```

## Test Categories

### Serial Port Tests (`test_serial_reader.py`)
- **Packet Parsing**: S0PCM-2 and S0PCM-5 telegram parsing
- **Connection Handling**: Connection, retry logic, error handling
- **Pulse Counting**: Increment detection, reset handling
- **Day Change**: Daily counter reset logic

### MQTT Tests (`test_mqtt_client.py`)
- **Connection**: Connect, disconnect, retry logic
- **Publishing**: Split topic and JSON modes
- **Discovery**: Home Assistant MQTT discovery
- **Commands**: Set total and name commands
- **State Recovery**: Recovery logic (ID mapping & value restoration)

### System Tests (`test_loops.py` & `test_main.py`)
- **Integration**: Proper thread initialization and data snapshotting
- **Lifecycle**: Graceful shutdown and signal handling (SIGINT/SIGTERM)

### Configuration Tests (`test_config.py`)
- **Loading**: From options.json and defaults (using Pathlib)
- **Validation**: Type checking and default values
- **Supervisor API**: Service discovery integration

## Key Testing Patterns

### Mocking Serial Port

```python
def test_serial_example(mock_serial):
    # mock_serial is automatically provided by conftest.py
    mock_serial.readline.return_value = b'ID:8237:I:10:M1:0:100:M2:0:50\r\n'
    # Your test code here
```

### Mocking MQTT Client

```python
def test_mqtt_example(mock_mqtt_client):
    # mock_mqtt_client is automatically provided by conftest.py
    mock_mqtt_client.connect.return_value = 0
    # Your test code here
```

### Using Fixtures

```python
def test_with_fixtures(s0pcm_packets, sample_measurement):
    # Use pre-defined test data from conftest.py
    header = s0pcm_packets['header']
    meter_data = sample_measurement[1]
    # Your test code here
```

## Important Notes

### Unified Module Structure

The script has been renamed from `s0pcm-reader.py` (hyphenated) to `s0pcm_reader.py` (underscore) to support standard Python imports. All tests directly import and exercise this module.

### State Management

Due to global state in `s0pcm_reader.py`, tests use strict state reset fixtures (see `conftest.py`) to ensure isolation.

### Threading Tests

Tests involving threads should:
1. Use short timeouts to prevent hanging
2. Always clean up threads (stop and join)
3. Use `threading.Event` for synchronization

Example:
```python
def test_thread_example():
    trigger = threading.Event()
    stopper = threading.Event()
    
    # Start thread
    thread = MyThread(trigger, stopper)
    thread.start()
    
    # Do test work
    
    # Clean up
    stopper.set()
    trigger.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
```

## Coverage

To generate a coverage report:

```bash
# Terminal output
pytest tests/ --cov=rootfs/usr/src --cov-report=term-missing

# HTML report (opens in browser)
pytest tests/ --cov=rootfs/usr/src --cov-report=html
open htmlcov/index.html
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines without requiring actual hardware (serial ports) or services (MQTT brokers).

## Troubleshooting

### Tests Hang
- Check for threads that aren't being stopped
- Ensure all `threading.Event` objects are set
- Use pytest timeout: `pytest --timeout=10`

### Import Errors
- Ensure `tests/requirements-test.txt` is installed
- Check Python path in `conftest.py`

### Mock Not Working
- Verify the patch path matches the import in the module
- Use `mocker.patch` instead of `@patch` decorator for better pytest integration

## Adding New Tests

1. Create test file: `tests/test_<feature>.py`
2. Import necessary fixtures from `conftest.py`
3. Use descriptive test names: `test_<what>_<condition>_<expected>`
4. Keep tests isolated and independent
5. Mock all external dependencies
6. Clean up resources (threads, files, etc.)

## Best Practices

✅ **DO**:
- Use fixtures for common setup
- Mock external dependencies
- Test edge cases and error conditions
- Keep tests fast (< 1 second each)
- Use descriptive assertions

❌ **DON'T**:
- Rely on actual serial ports or MQTT brokers
- Share state between tests
- Use sleep() for synchronization (use Events)
- Test multiple things in one test
- Leave threads running

## Further Reading

- [pytest documentation](https://docs.pytest.org/)
- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
