# S0PCM Reader for Home Assistant

[![GitHub Release][releases-shield]][releases] [![Add to Home Assistant][my-ha-shield]][my-ha] [![Reported Installations][installations-shield-stable]][installations-link]

An easy-to-use Home Assistant App that reads pulse counters from an **S0PCM-2** or **S0PCM-5** device and sends the data to Home Assistant via MQTT.

This app is based on the [docker-s0pcm-reader](https://github.com/ualex73/docker-s0pcm-reader) by @ualex73.

## ✨ Features

- **MQTT Auto-Discovery**: Automatically creates sensors in Home Assistant for all enabled inputs.
- **Native Configuration**: Rename meters and correct totals directly from the **Device** page in Home Assistant UI—no YAML or manual MQTT actions required.
- **Dual-Layer State Recovery**: Robust restoration of meter data from both MQTT (primary) and the Home Assistant API (secondary fallback), ensuring no data loss even in a total wipeout.
- **Professional Quality Assurance**: Verified by a robust battery of **111 unit and integration tests** achieving **88% total coverage** (95% critical path coverage).
- **Modular Redesign**: Fully refactored in **v3.0.0** into a clean, modular architecture for superior maintainability and performance, utilizing robust multithreaded execution.
- **Type Safety & Validation**: Built with typed **Pydantic v2** models for industrial-grade configuration and state validation.
- **TLS Support**: Secure your MQTT connection with TLS, featuring automatic fallback to plain MQTT if TLS fails.
- **Watchdog / Auto-restart**: Built on S6-overlay for robust process supervision and automatic recovery.
- **Real-time Error Reporting**: Dedicated MQTT topic and diagnostic sensor for instant feedback on serial or configuration issues.
- **Diagnostic Metadata**: New `info` topic and sensor providing versioning, hardware firmware, and uptime details.
- **Industrial-Grade Tooling**: Integrated **Ruff** for high-speed linting and formatting, ensuring professional code quality standards and caught potential issues early.
- **Flexible MQTT**: Supports external brokers, authentication, and custom base topics.

## ⚠️ Migration to v3.0.0

Version 3.0.0 is a major release with a completely rewritten modular architecture.

> [!WARNING]
> **Breaking Change**: The local `measurement.json` file has been removed. The app now relies exclusively on **MQTT retained messages** and the **Home Assistant API** for state persistence.
>
> **How to migrate**:
> 1. Ensure your MQTT broker has persistence enabled (default in Mosquitto).
> 2. Upon first startup of v3.0.0, the app will automatically recover your totals from Home Assistant.
> 3. Verify your totals in the HA UI. If adjustments are needed, use the new **Total Correction** entity on the device page.

## 🛠️ Prerequisites

- An **S0PCM reader** (S0PCM-2 or S0PCM-5) connected via USB.
- An **MQTT Broker** (e.g., the official Mosquitto broker app).

## 🚀 Installation (Recommended & Supported method)

1. Add this repository to your Home Assistant App Store:
   `https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader`
2. Search for **S0PCM Reader** and click **Install**.
3. Navigate to the **Configuration** tab.
4. Select your **S0PCM USB device** (e.g., `/dev/ttyACM0`).
5. **Start** the app.

## 🐳 Home Assistant Container (Standalone & Advanced method, only use if you know what you're doing)

> [!IMPORTANT]
> **Community Support Only**: This configuration is intended for advanced users. Official support is only provided for the standard Home Assistant App installation. Use this at your own risk.

If you are running Home Assistant in a standalone Docker container (without Supervisor/Apps), you can run this reader as a standalone container.

### Quick Start (Local Build)

1. **Clone the repo**: `git clone https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader.git`
2. **Configure**: Create a `config/options.json` file inside the cloned directory. Since you are not using the Supervisor, you **must** manually specify your MQTT broker details:

```json
{
  "device": "/dev/ttyACM0",
  "mqtt_host": "192.168.1.50",
  "mqtt_username": "your_user",
  "mqtt_password": "your_password",
  "mqtt_base_topic": "s0pcmreader",
  "log_level": "info"
}
```
*(Refer to `DOCS.md` for a full list of available keys.)*

### Key Reference for `options.json`

| Key | Description | Default |
| :--- | :--- | :--- |
| `device` | Serial port (e.g. `/dev/ttyUSB0`) | `/dev/ttyACM0` |
| `mqtt_host` | MQTT Broker address | `core-mosquitto` |
| `mqtt_port` | MQTT Broker port | `1883` |
| `mqtt_username` | MQTT Username | (none) |
| `mqtt_password` | MQTT Password | (none) |
| `mqtt_base_topic`| Root MQTT topic | `s0pcmreader` |
| `log_level` | `info`, `debug`, `error` | `info` |

3. **Launch**: Use the following `docker-compose.yml` snippet:

```yaml
services:
  s0pcm-reader:
    build: 
      context: .
      dockerfile: Dockerfile.standalone
    container_name: s0pcm-reader
    restart: unless-stopped
    devices:
      - /dev/ttyACM0:/dev/ttyACM0 # Adjust to your port
    volumes:
      - ./config:/data
```

## 📖 Documentation

Detailed documentation, including configuration guides and advanced settings, can be found in the **Documentation** tab within the Home Assistant app interface.

### [Full Documentation (GitHub)](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md)
*Use this link if you are viewing the repository on GitHub.*

## 🧪 Development & Testing

This project maintains high reliability through multiple testing layers including Unit Tests, Hardware Simulation (`socket://`), and a Standalone Verification Suite.

Detailed instructions for running tests and simulators can be found in [tests/README.md](tests/README.md).

To run the full verification suite locally:
- **Windows**: `PowerShell -File ./tests/docker-test.ps1`
- **Linux/macOS**: `./tests/docker-test.sh`

## 🤝 Support

If you encounter issues or have suggestions, please [open an issue](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/issues) on GitHub.

[releases-shield]: https://img.shields.io/github/v/release/darkrain-nl/home-assistant-addon-s0pcm-reader?include_prereleases&style=flat-square
[releases]: https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/releases
[installations-shield-stable]: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Faddons.json&query=%24%5B%224a252ed0_s0pcm_reader%22%5D.total&label=Reported%20Installations&color=0382B9&style=flat-square
[installations-link]: https://analytics.home-assistant.io/add-ons
[my-ha-shield]: https://my.home-assistant.io/badges/supervisor_add_repository.svg
[my-ha]: https://my.home-assistant.io/redirect/supervisor_add_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdarkrain-nl%2Fhome-assistant-addon-s0pcm-reader