# S0PCM Reader for Home Assistant

[![GitHub Release][releases-shield]][releases] [![Add to Home Assistant][my-ha-shield]][my-ha] [![Reported Installations][installations-shield-stable]][installations-link]

An easy-to-use Home Assistant App that reads pulse counters from an **S0PCM-2** or **S0PCM-5** device and sends the data to Home Assistant via MQTT.

## ✨ Features

- **Plug & Play**: Automatically shows up in Home Assistant (MQTT Discovery).
- **Easy Configuration**: Rename meters and fix totals directly in Home Assistant - no editing files.
- **Reliable**: Restores your meter data on restart so you don't lose counts.
- **Simple & Clean**: No local database files to worry about.
- **Secure**: Supports MQTT with TLS encryption.
- **Instant Issues**: Reports connection errors immediately so you know if something is wrong.

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

## 📖 Documentation

For detailed configuration, advanced settings, and standalone usage (Docker), please refer to the full documentation:

**In Home Assistant:** Go to the **Documentation** tab.

**On GitHub:** [View Full Documentation (DOCS.md)](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md)

### Quick Links (GitHub Only)
- [Configuration Reference](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md#3-configuration)
- [Home Assistant Integration & Recipes](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md#5-home-assistant-integration-cookbook)
- [Standalone / Docker Usage](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md#standalone-docker-container-advanced)
- [Troubleshooting](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/blob/main/DOCS.md#6-troubleshooting)

## 🧪 Development & Testing

If you want to contribute or modify the code, we have included a test suite and a hardware simulator (`socket://`).

Check out [tests/README.md](tests/README.md) to see how to run it locally.

## 🤝 Support

If you encounter issues or have suggestions, please [open an issue](https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/issues) on GitHub.

## ❤️ Credits

Inspired by the [docker-s0pcm-reader](https://github.com/ualex73/docker-s0pcm-reader) project by @ualex73.

[releases-shield]: https://img.shields.io/github/v/release/darkrain-nl/home-assistant-addon-s0pcm-reader?include_prereleases&style=flat-square
[releases]: https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/releases
[installations-shield-stable]: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Faddons.json&query=%24%5B%224a252ed0_s0pcm_reader%22%5D.total&label=Reported%20Installations&color=0382B9&style=flat-square
[installations-link]: https://analytics.home-assistant.io/add-ons
[my-ha-shield]: https://img.shields.io/badge/Add%20to-Home%20Assistant-41BDF5?style=flat-square&logo=home-assistant

[my-ha]: https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdarkrain-nl%2Fhome-assistant-addon-s0pcm-reader