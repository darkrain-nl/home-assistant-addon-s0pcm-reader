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
├── standalone/               # Integrated E2E verification stack
├── conftest.py               # Shared fixtures (Mocks for Serial, MQTT, API)
├── pytest.ini                # Pytest & Coverage configuration
├── requirements-test.txt     # Test dependencies
├── docker-test.ps1           # Windows Dockerized test runner
├── docker-test.sh            # Linux/Mac Dockerized test runner
├── Dockerfile.test           # Test container definition
├── test_config.py            # Config loading & validation tests
├── test_discovery.py         # MQTT discovery message tests
├── test_mqtt_handler.py      # MQTT publishing & TLS logic tests
├── test_protocol.py          # S0PCM telegram parsing tests
├── test_recovery.py          # State recovery & HA API fallback tests
├── test_s0pcm_reader.py      # Main loop & signal handling tests
├── test_serial_handler.py    # Serial connection & socket logic tests
├── test_state.py             # Internal state management tests
└── test_utils.py             # Utility function & logging tests
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

## 📡 Hardware Simulation & Integrated Testing

### 1. Serial-over-TCP Simulation
The S0PCM Reader supports `socket://<host>:<port>` URLs in the `device` configuration. This allows testing against simulated hardware over a network.

- **Example**: Set `"device": "socket://127.0.0.1:2000"` in `options.json`.
- **Packet Format**: The app expects standard S0PCM hex telegrams (e.g. `ID:0 ...`) followed by `\n`.

### 2. Standalone Verification Suite
For full end-to-end testing, we use a dedicated Docker Compose stack located in `tests/standalone/`. This stack includes:
- **App**: The S0PCM Reader configured for standalone mode.
- **Simulator**: A Python-based TCP server (`simulator.py`) that generates virtual S0PCM packets.
- **MQTT**: A Mosquitto broker with a healthcheck configuration.

To run the verification suite:
```bash
docker compose -f tests/standalone/docker-compose.yml up --build --exit-code-from app
```

### 3. Integrated Test Runners
The `docker-test.ps1` (Windows) and `docker-test.sh` (Linux) scripts perform the following steps:
1. Build and run the **Unit Test** container.
2. Build and run the **Standalone Verification** stack.
3. Verify that the app successfully connects to MQTT in the integrated environment.

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
*Last updated: 2026-01-31*
