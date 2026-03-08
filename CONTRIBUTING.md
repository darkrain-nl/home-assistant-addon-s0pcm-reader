# Contributing to S0PCM Reader

Thank you for your interest in contributing! This guide will help you get started.

## Architecture

### "Dumb Driver" Philosophy

This app is designed to be a **pure hardware driver**. Its sole responsibility is to:
1. Read raw pulse counts from the S0PCM USB stick.
2. Publish those raw counts to MQTT.

**We do NOT implement** unit conversions (pulses → m³), flow rates (L/min), cost tracking, or historical statistics. Home Assistant already has powerful native tools for this (Template Sensors, Utility Meters, Riemann Sum Integration). See the [Cookbook in DOCS.md](DOCS.md#5-home-assistant-integration-cookbook) for examples.

If a feature request asks for calculations inside the app, point the user to the DOCS.md Cookbook instead.

## Project Structure

```text
rootfs/usr/src/          # Application source code
  ├── s0pcm_reader.py    # Main entry point
  ├── config.py          # Configuration loading & validation
  ├── mqtt_handler.py    # MQTT connection & publishing
  ├── serial_handler.py  # Serial port communication
  ├── discovery.py       # Home Assistant MQTT Discovery
  ├── recovery.py        # State recovery (MQTT + HA API fallback)
  ├── protocol.py        # S0PCM telegram parsing
  ├── state.py           # Internal state management
  ├── constants.py       # Shared constants
  └── healthcheck.py     # Docker health monitoring
tests/                   # Test suite (see tests/README.md)
translations/            # Home Assistant UI translations
config.yaml              # Home Assistant App manifest
```

## Development Setup

### Prerequisites
- **Docker** (required for running tests and linting)
- **Python 3.14+** (optional, for local IDE support)

### Running Tests
Tests run in Docker for environment consistency. From the project root:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File .\tests\docker-test.ps1

# Linux / Mac
./tests/docker-test.sh
```

For detailed testing instructions (targeted tests, coverage, hardware simulation), see [tests/README.md](tests/README.md).

### Linting
We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. Configuration is in `pyproject.toml`.

```powershell
# Auto-fix all issues (Windows)
powershell -ExecutionPolicy Bypass -File .\tests\fix-lint.ps1
```

> [!IMPORTANT]
> Always run the linter **before** running tests. The test suite enforces formatting compliance.

## Code Standards

- **Full test coverage** is required. If you add or modify code, you must write tests to cover all branches. Use of `# pragma: no cover` is restricted to standard guard clauses (e.g., `if __name__ == "__main__":`).
- **Ruff linting** must pass with zero warnings. Run the linter before committing.
- **Terminology**: Use "App" instead of "Add-on" or "Addon" in all user-facing text (`README.md`, `DOCS.md`, `translations/en.yaml`). Historical `CHANGELOG.md` entries are not updated.
- **No hardcoded metrics** in documentation — don't put specific test counts or coverage percentages in README, DOCS, etc.

## Release Process

1. **Bump the version** in both `config.yaml` and `pyproject.toml` (they must match).
2. **Add a CHANGELOG entry** following [Keep a Changelog](https://keepachangelog.com/) format.
3. **Verify documentation** (`README.md`, `DOCS.md`, `tests/README.md`) is up to date.
4. **Merge to `main`** via PR from `dev`.

A GitHub Actions workflow will automatically create a tag and GitHub Release from the CHANGELOG.

## Submitting Changes

1. Fork the repository and create a branch from `dev`.
2. Make your changes and ensure tests pass with full coverage.
3. Run the linter and fix any issues.
4. Open a Pull Request against the `dev` branch.

## Questions?

If you have questions or run into issues, please [open an issue](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/issues) on GitHub.
