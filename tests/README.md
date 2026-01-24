# S0PCM Reader Tests

This directory contains the comprehensive test suite for the S0PCM Reader Home Assistant addon.

## 🚀 Quick Start

### Local Testing (Python Environment)
```bash
# 1. Install dependencies
pip install -r tests/requirements-test.txt

# 2. Run all tests
pytest tests/

# 3. Run with coverage
pytest tests/ --cov=rootfs/usr/src --cov-report=term-missing
```

### Docker Testing (Recommended)
This method ensures environment parity with CI/CD without needing Python installed locally.
```powershell
# Windows (PowerShell)
.\tests\docker-test.ps1

# Linux / Mac (Bash)
./tests/docker-test.sh
```

---

## 📂 Test Structure

```text
tests/
├── conftest.py              # Shared fixtures (Mocks for Serial, MQTT, API)
├── pytest.ini               # Pytest & Coverage configuration
├── requirements-test.txt    # Test dependencies
├── docker-test.ps1/sh       # Dockerized test runners
├── Dockerfile.test          # Test container definition (Python 3.14)
├── test_config.py           # Config loading & validation tests
├── test_loops.py            # Main thread integration tests
├── test_main.py             # Startup & Signal handling tests
├── test_measurement_logic.py # Data processing & conversion tests
├── test_mqtt_client.py      # MQTT publishing & recovery tests
├── test_packet_parsing.py   # S0PCM telegram parsing tests
└── test_serial_reader.py    # Serial connection & pulse logic tests
```

---

## 🛠️ Testing Manual

### 1. Mocking External Dependencies
All external systems are mocked in `conftest.py`. Mocks are automatically injected into tests using the `mocker` fixture.

**Example: Mocking MQTT**
```python
def test_mqtt_example(mock_mqtt_client):
    # mock_mqtt_client is automatically provided
    mock_mqtt_client.connect.return_value = 0
    # Your test code here
```

### 2. Manual Docker Build & Run
If you prefer running manual commands from the **project root**:
```bash
# Build
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .

# Run
docker run --rm s0pcm-reader-test
```

### 3. Continuous Integration
Tests run automatically via GitHub Actions on every push to `main` and `dev`. Results are uploaded to **Codecov**.

---

## 🔧 Troubleshooting

### Pytest Cache / Read-only Filesystems
If running in a strictly read-only environment, the cache provider is disabled via `pytest.ini` (`-p no:cacheprovider`) to prevent `PytestCacheWarning`.

### Tests Hanging
Hanging tests usually indicate an unstopped thread. Ensure all `threading.Event` objects (like `stopper`) are set during cleanup:
```python
stopper.set()
trigger.set()
thread.join(timeout=5)
```

### Script Execution Policy (Windows)
If `.ps1` scripts are blocked, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---
*Last updated: 2026-01-24*
