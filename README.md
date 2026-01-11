# S0PCM Reader for Home Assistant

[![GitHub Release][releases-shield]][releases]
![Reported Installations][installations-shield-stable]

An easy-to-use Home Assistant Add-on that reads pulse counters from an **S0PCM-2** or **S0PCM-5** device and sends the data to Home Assistant via MQTT.

This add-on is based on the [docker-s0pcm-reader](https://github.com/ualex73/docker-s0pcm-reader) by @ualex73.

## ✨ Features

- **MQTT Auto-Discovery**: Automatically creates sensors in Home Assistant for all enabled inputs.
- **Native Configuration**: Rename meters and correct totals directly from the **Device** page in Home Assistant UI—no YAML or manual MQTT actions required.
- **Dual-Layer State Recovery**: Robust restoration of meter data from both MQTT (primary) and the Home Assistant API (secondary fallback), ensuring no data loss even in a total wipeout.
- **TLS Support**: Secure your MQTT connection with TLS, featuring automatic fallback to plain MQTT if TLS fails.
- **Watchdog / Auto-restart**: Built on S6-overlay for robust process supervision and automatic recovery.
- **Real-time Error Reporting**: Dedicated MQTT topic and diagnostic sensor for instant feedback on serial or configuration issues.
- **Diagnostic Metadata**: New `info` topic and sensor providing versioning, hardware firmware, and uptime details.
- **Flexible MQTT**: Supports external brokers, authentication, and custom base topics.

## 🛠️ Prerequisites

- An **S0PCM reader** (S0PCM-2 or S0PCM-5) connected via USB.
- An **MQTT Broker** (e.g., the official Mosquitto broker add-on).

## 🚀 Installation

1. Add this repository to your Home Assistant Add-on store:
   `https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader`
2. Search for **S0PCM Reader** and click **Install**.
3. Navigate to the **Configuration** tab.
4. Select your **S0PCM USB device** (e.g., `/dev/ttyACM0`).
5. **Start** the add-on.

## 📖 Documentation

Detailed documentation, including configuration guides and advanced settings, can be found in the **Documentation** tab within the Home Assistant add-on interface.

### [Full Documentation (GitHub)](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md)
*Use this link if you are viewing the repository on GitHub.*

## 🤝 Support

If you encounter issues or have suggestions, please [open an issue](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/issues) on GitHub.

[releases-shield]: https://img.shields.io/github/v/release/darkrain-nl/home-assistant-addon-s0pcm-reader?include_prereleases
[releases]: https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/releases
[installations-shield-stable]: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Faddons.json&query=%24%5B%224a252ed0_s0pcm_reader%22%5D.total&label=Reported%20Installations&link=https%3A%2F%2Fanalytics.home-assistant.io/add-ons