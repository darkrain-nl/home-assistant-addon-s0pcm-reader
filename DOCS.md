# S0PCM Reader - Documentation

## 1. Introduction

This application reads pulse counts from S0PCM-2 (2-channel) or S0PCM-5 (5-channel) USB devices and publishes them to Home Assistant via MQTT. It is designed to be a robust "hardware driver" that handles the serial communication and state recovery, leaving high-level logic (like cost calculation) to Home Assistant.

## 2. Installation Methods

### Home Assistant Add-on (Recommended)
1. Add the repository: `https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader`
2. Install **S0PCM Reader** from the Add-on Store.
3. Configure the **Device** (e.g., `/dev/ttyACM0`) in the Configuration tab.
4. Start the add-on.

### Standalone Docker Container (Advanced)
If you are not using Home Assistant OS/Supervisor, you can run this as a standalone container.

**1. Create a `config/options.json` file:**
```json
{
  "device": "/dev/ttyACM0",
  "mqtt_host": "192.168.1.50",
  "mqtt_username": "user",
  "mqtt_password": "password",
  "mqtt_base_topic": "s0pcmreader",
  "log_level": "info"
}
```

**2. Run with Docker Compose:**
```yaml
services:
  s0pcm-reader:
    # Build locally from the repository
    build:
      context: .
      dockerfile: Dockerfile.standalone
    container_name: s0pcm-reader
    restart: unless-stopped
    devices:
      - /dev/ttyACM0:/dev/ttyACM0
    volumes:
      - ./config:/data
```

## 3. Configuration

### General Options
- **Device**: Path to the USB device (e.g., `/dev/ttyACM0`).
- **Log Level**: (Default: `info`) Set logging verbosity (`debug`, `info`, `warning`, `error`, `critical`).

### Connection Settings
- **MQTT Host**: Internal broker is used by default. Set this for external brokers.
- **MQTT Port**: Default `1883` (or `8883` if TLS is enabled).
- **MQTT Username**: Username for the broker.
- **MQTT Password**: Password for the broker.
- **MQTT Client ID**: (Optional) Custom client ID for the connection.

### Advanced MQTT Settings
- **MQTT Base Topic**: Root topic (Default `s0pcmreader`). Changing this creates a new device in Home Assistant.
- **MQTT Protocol**: (Default: `5.0`) Select MQTT protocol version (`3.1`, `3.1.1`, or `5.0`).
- **MQTT Discovery**: (Default: `true`) Enable Home Assistant auto-discovery.
- **MQTT Discovery Prefix**: (Default: `homeassistant`) Prefix for discovery topics.
- **MQTT Retain**: (Default: `true`) Retain messages for persistence.
- **MQTT Split Topic**: (Default: `true`) Use split topic structure (recommended).
- **Recovery Wait Time**: (Default: `7s`) Time to wait for MQTT retained messages on startup. **Do not lower** this unless you have fast hardware, or you risk data loss.

### Security Settings (TLS)
- **MQTT TLS**: (Default: `false`) Enable TLS encryption. The connection will **not** fall back to plaintext if TLS fails.
- **MQTT TLS Port**: (Default: `8883`) Port to use for TLS connections.
- **MQTT TLS CA**: (Optional) Path to a custom CA certificate file.
- **MQTT Check Peer**: (Default: `false`) Verify the server's certificate. Disabled by default for compatibility with self-signed certs.

> [!NOTE]
> When TLS is enabled without a CA certificate, the connection is encrypted but the server's identity is **not verified**. This is safe on a local Home Assistant OS setup. If you connect to an external broker over an untrusted network, provide a CA certificate and enable **MQTT Check Peer**.

## 4. Usage Guide

### Naming Meters
You can rename meters directly from the Home Assistant UI.
1. Go to **Settings > Devices & Services > Devices**.
2. Find **S0PCM Reader**.
3. Change the value in the **"Name"** text entity (e.g., `text.1_name` -> `Kitchen Water`).
4. The sensors in HA will automatically update to `sensor.kitchen_water_total`.

### Correcting Totals
To sync the app with your physical meter:
1. Go to the **S0PCM Reader** device page.
2. Find the **"Total Correction"** number entity (e.g., `number.1_total_correction`).
3. Set the correct value and press enter. The `total` sensor will update immediately.

## 5. Home Assistant Integration (Cookbook)

The addon provides **raw pulse counts** (e.g., `12345` pulses). To make this useful, use Home Assistant's native helpers.

### Recipe 1: Convert to Units (m³ or kWh)
Create a **Template Sensor** to convert raw pulses to your desired unit (e.g., 1000 pulses = 1 m³).

1. **Settings > Devices & Services > Helpers > Create Helper > Template > Template a sensor**.
2. **Name**: `Water Usage`
3. **State Template**:
   ```
   {{ (states('sensor.s0pcm_s0pcmreader_1_total') | float(0) / 1000) | round(3) }}
   ```
4. **Availability Template**:
   ```jinja
   {{ has_value('sensor.s0pcm_s0pcmreader_1_total') }}
   ```
5. **Unit**: `m³`
6. **Class**: `Water`
7. **State Class**: `Total increasing`

### Recipe 2: Live Flow Rate / Power
Use the **Derivative** helper to calculate flow rate (L/min) or power (Watts) from the total counter.

1. **Settings > Devices & Services > Helpers > Create Helper > Derivative sensor**.
2. **Input Sensor**: The *Template Sensor* you created above (e.g., `Water Usage`).
3. **Time Window**: `00:01:00` (1 minute smoothing).
4. **Unit**: `h` (for m³/h) or `min` (for L/min).

### Recipe 3: Energy Dashboard
Once you have created the **Template Sensor** (Recipe 1) with correct device class (`Water` or `Energy`) and state class (`Total increasing`), it will automatically appear as a selectable source in the **Energy Dashboard** settings.

## 6. Legacy Configuration (YAML)

> [!NOTE]
> This section is only for users who **disable MQTT Discovery** or prefer manual YAML configuration.

If you set `mqtt_discovery: false`, you can manually configure sensors in your `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - state_topic: "s0pcmreader/1/total"
      availability_topic: "s0pcmreader/status"
      name: "Water Multiplier"
      unique_id: "water_multiplier"
      # Example: Convert pulses to m3
      value_template: "{{ value | float / 1000 }}"
      unit_of_measurement: "m³"
      state_class: total_increasing
      device_class: water
```

## 7. Troubleshooting

### Common Issues
- **"Connection Refused"**: Check if MQTT broker is running.
- **"Serial Port Not Found"**: Check USB connection and "Hardware" tab in HA OS.
- **Sensors "Unavailable"**: 
  - If the addon is disconnected from the MQTT broker (e.g., during a restart), sensors will automatically show as "Unavailable" to prevent stale data. They will recover once reconnected.
  - If they never recover, did you change the MQTT Base Topic? This creates a new device.

### State Recovery
The app uses a dual-layer recovery system:
1.  **MQTT Retain**: Primary recovery source.
2.  **HA API**: Fallback if MQTT is empty.

**Note**: If you wipe both MQTT and restart HA simultaneously, data may be lost. **Always backup your MQTT broker.**

## 8. Technical Details
- **Architecture**: Multithreaded Python app.
- **Discovery**: Follows Home Assistant MQTT Discovery standard.
- **Topics**:
    - Data: `s0pcmreader/<ID>/total`
    - Diagnostics: `s0pcmreader/status`, `s0pcmreader/error`