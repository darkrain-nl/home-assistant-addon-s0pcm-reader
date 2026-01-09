# S0PCM Reader add-on documentation

## MQTT Discovery

The add-on supports Home Assistant MQTT Discovery, which is **enabled by default**. This means you generally do **not** need to manually configure sensors in your `configuration.yaml` anymore.

When the add-on starts, it automatically creates a device named **S0PCM Reader** in Home Assistant with the following sensors for each enabled input:
- **Total**: Total accumulated count.
- **Today**: Count for the current day.
- **Yesterday**: Count for the previous day.
- **Status**: A binary sensor showing if the reader is connected to MQTT.
- **Error**: A diagnostic sensor that displays the last error encountered.
- **Addon Version**: Current version of the S0PCM Reader addon.
- **S0PCM Firmware**: Firmware version reported by the hardware.
- **Startup Time**: Timestamp of when the addon started.
- **Serial Port**: The configured USB/serial port.
**Naming:**
The entity names and MQTT topics are derived from the `name` field in your `measurement.json`. If you haven't configured a name, it defaults to the numerical input ID (e.g., "1 Total"). 

> [!TIP]
> You can easily set or change these names via MQTT. See the **Naming Your Meters** section below for details.

> [!TIP]
> **Historic Data**: Your historical data in Home Assistant is safely preserved even if you change the name of a meter. The addon uses a stable `unique_id` based on the numerical input ID, so Home Assistant will keep the data linked even if you rename "Meter 1" to "Water".

### Measurement Configuration (`measurement.json`)

This file is now stored in the addon's private `/data` folder. While it is automatically managed by the addon, you can restore or initialize your totals using MQTT (see the **State Recovery** section below).

**Example:**
```json
{
    "date": "2026-01-08",
    "1": {
        "pulsecount": 0,
        "today": 194,
        "total": 1322738,
        "yesterday": 139
    },
    "2": {
        "pulsecount": 0,
        "today": 0,
        "total": 0,
        "yesterday": 0,
        "name": "Water"
    }
}
```

In this example:
- **Meter 1** does not have a custom name. Its sensors will be published to `s0pcmreader/1/total`, etc., and appear in Home Assistant as "1 Total", "1 Today", etc.
- **Meter 2** has the custom name "Water". Its sensors will be published to `s0pcmreader/Water/total`, etc., and appear in Home Assistant as "Water Total", "Water Today", etc.

> [!TIP]
> You can now use either the **Meter Name** or the **Meter ID** for setting totals (e.g., `s0pcmreader/Water/total/set` or `s0pcmreader/2/total/set`).

## Configuration via Home Assistant UI

You can configure the following options directly in the **Settings > Add-ons > S0PCM Reader > Configuration** tab in Home Assistant:

### Required Settings
- **Device**: The serial port device (e.g., `/dev/ttyACM0`).

### Optional Settings

> [!NOTE]
> Most optional settings are hidden by default for a cleaner interface. Click **"Show unused optional configuration options"** in the Home Assistant UI to reveal additional settings like MQTT host, port, protocol, discovery options, and more. All hidden settings have sensible defaults that work out-of-the-box.

#### General
- **Log Level**: The detail of the logs (debug, info, warning, error, critical). Defaults to `info`. Logs are streamed directly to the Home Assistant addon console.

#### Connection Options
- **MQTT Host**: Manual host for an external broker. If not set, it uses the internally discovered broker (typically `core-mosquitto`).
- **MQTT Port**: The port for unencrypted MQTT. Defaults to `1883`.
- **MQTT Username**: Manual username for an external broker.
- **MQTT Password**: Manual password for an external broker.
- **MQTT Client ID**: Unique ID for the MQTT client. Defaults to auto-generated.
- **MQTT Base Topic**: The base topic for all MQTT messages. Defaults to `s0pcmreader`.
- **MQTT Protocol**: MQTT protocol version (5.0, 3.1.1, or 3.1). Defaults to `5.0`.

#### Advanced MQTT Options
- **MQTT Discovery**: Enable or disable Home Assistant auto-discovery. Defaults to `true`.
- **MQTT Discovery Prefix**: Discovery prefix for Home Assistant. Defaults to `homeassistant`.
- **MQTT Retain**: Enable or disable message retention on the broker. Defaults to `true`.
- **MQTT Split Topic**: Enable or disable split topics (separate topics for total/today/yesterday vs. JSON). Defaults to `true`.

#### Security Options
- **MQTT TLS**: Enable or disable TLS for MQTT. Defaults to `false`.
- **MQTT TLS Port**: The port for encrypted MQTT. Defaults to `8883`.
- **MQTT TLS CA**: Filename or full path to your CA certificate.
- **MQTT TLS Check Peer**: Enable or disable certificate and hostname verification. Defaults to `false`.

> [!NOTE]
> All configuration is now managed directly through the Home Assistant UI. Legacy manual `configuration.json` files are no longer required or recommended.

## Setting Meter Totals

You can update the total value of any meter (e.g., to sync with a physical meter) using either MQTT or the Home Assistant UI.

### Option 1: Using Home Assistant Actions (Recommended)

1. Go to **Developer Tools** > **Actions**.
2. Search for **MQTT: Publish**.
3. Fill in the details:
   - **Topic**: `s0pcmreader/Water/total/set` (or use the ID: `s0pcmreader/1/total/set`)
   - **Payload**: `123456`
   
> [!NOTE]
> You can use either the numerical **Meter ID** or your custom **Meter Name** (case-insensitive) in the topic. The addon will automatically find the correct meter to update.

4. Click **Perform Action**.

### Option 2: Using raw MQTT

Send an MQTT message to the following topic:
**Topic:** `<base_topic>/<name_or_id>/total/set`
**Payload:** The new integer value for the total.

> [!TIP]
> You can use either the numerical **Meter ID** (1, 2, 3, etc.) or the custom **Meter Name** (if configured) in the set topic.

**Example:**
`mosquitto_pub -t "s0pcmreader/Water/total/set" -m "1000"`
or
`mosquitto_pub -t "s0pcmreader/1/total/set" -m "1000"`

> [!NOTE]
> This command only updates the **Total** counter. The **Today** and **Yesterday** counters remain unchanged and will continue to count based on the pulses received relative to the previous day's total.

## Naming Your Meters

Since measurement data is now stored in a private folder for better security and performance, you can no longer edit the data file manually. Instead, you can set (or change) meter names via MQTT.

### Option 1: Using Home Assistant Actions (Recommended)

1. Go to **Developer Tools** > **Actions**.
2. Search for **MQTT: Publish**.
3. Fill in the details:
   - **Topic**: `s0pcmreader/<ID>/name/set` (e.g., `s0pcmreader/1/name/set`)
   - **Payload**: `Kitchen` (or whatever you want to name it)
4. Click **Perform Action**.

### Option 2: Using raw MQTT

Send an MQTT message to the following topic:
**Topic:** `<base_topic>/<ID>/name/set`
**Payload:** Your desired meter name.

> [!TIP]
> To remove a name and revert to the default ID-based name, simply send an **empty payload** to the `name/set` topic.

The addon will immediately:
- Update the internal name for that meter.
- Save the change permanently.
- Re-send MQTT Discovery messages to update the sensor names in Home Assistant.

## MQTT Error Reporting

The add-on monitors its internal operations and reports any issues to the `<base_topic>/error` topic. If MQTT Discovery is enabled, this will appear as an **Error** sensor in Home Assistant.

**Reported errors include:**
- **Serial Connection Failures:** If the S0PCM device is unplugged or the port is invalid.
- **MQTT Connection Issues:** If the broker is unreachable or the connection is lost (reported once reconnected).
- **Packet Parsing Issues:** If the data received from the S0PCM is corrupted or in an unknown format.
- **MQTT Command Errors:** If an invalid payload is sent to a `/total/set` topic.
- **Pulsecount Anomalies:** If a sudden jump or reset in pulse count is detected (e.g., after an S0PCM restart).

Once the issue is resolved and a valid data packet is successfully processed, the error sensor will automatically clear itself and display **"No Error"**.

## MQTT TLS Support

The add-on supports secure MQTT connections using TLS.

> [!WARNING]
> **Security Notice**: This addon defaults to unencrypted MQTT for ease of setup with local brokers. If your MQTT broker is exposed to external networks or you want additional security, enable the **mqtt_tls** option in the **Configuration** tab.

- **Automatic Fallback:** If TLS connection fails (e.g., certificate error), the add-on will automatically fall back to a plain non-encrypted connection to ensure stable operation.
- **Port Swapping:** By default, the addon uses **MQTT Port** for plain connections and **MQTT TLS Port** for encrypted connections.
- **Insecure by Default:** Certificate validation is disabled by default (`mqtt_tls_check_peer: false`) for compatibility with local brokers using self-signed certificates. To enable strict verification, set `mqtt_tls_check_peer` to `true`.
- **CA Certificate:** Provide the path to your CA certificate.
  - **Recommended:** Put your certificate in the Home Assistant `/ssl/` folder (accessible via Samba/SSH) and use the absolute path: `/ssl/your-ca.crt`.

## State Recovery & Data Safety

This addon implements a robust state recovery mechanism. If the local `measurement.json` is missing (e.g., after an addon uninstallation and reinstallation), the addon will attempt to recover your meter totals from the MQTT broker.

1. On startup, the addon connects to MQTT.
2. It listens for 5 seconds for any **retained messages** on the topics `<base_topic>/+/total`, `<base_topic>/+/today`, and `<base_topic>/+/yesterday`.
3. Any totals or daily counts found are automatically applied to the local state and saved.

> [!CAUTION]
> **Backup Advice**: The MQTT recovery mechanism relies on your MQTT broker (e.g., Mosquitto) being active and having retained messages. **If you uninstall both this addon and your MQTT broker at the same time, your meter totals will be permanently lost.**
> 
> To ensure your data is safe:
> - **Enable Home Assistant Backups**: Regularly back up your Home Assistant instance. This is the most reliable way to restore both addon and broker data.
> - **Verify Retention**: Most modern brokers retain these messages by default, but it is always good practice to verify your totals are correct after a restoration.

## Watchdog / Auto-restart

This add-on uses the [S6 Overlay](https://github.com/just-containers/s6-overlay) for process supervision. If the S0PCM reader script crashes or exits unexpectedly, it will be automatically restarted.

## MQTT Message Details

The following MQTT messages are sent:

```
<base_topic>/<name_or_id>/total
<base_topic>/<name_or_id>/today
<base_topic>/<name_or_id>/yesterday
<base_topic>/status
<base_topic>/error
<base_topic>/version
<base_topic>/firmware
<base_topic>/startup_time
<base_topic>/port
<base_topic>/info  (JSON containing all diagnostic info)
```

If `mqtt_split_topic` is set to `false`, the **meter readings** are sent as a JSON string to a single topic. Diagnostic sensors (Status, Error, Version, etc.) are **always** sent to their own separate topics regardless of this setting.

`base_topic/1` -> `{"total": 12345, "today": 15, "yesterday": 77}`

## Using Data in the Energy Dashboard (UI Helpers)

To use your meter data in the Home Assistant Energy Dashboard, you need to create a **Template Sensor** helper. This is the recommended way to convert the pulse counts into units like m³ or kWh while ensuring all required metadata is present.

1. Go to **Settings** > **Devices & Services** > **Helpers**.
2. Click **+ Create Helper** and select **Template** > **Template a sensor**.
3. Fill in the following details:
   - **Name**: e.g., `Water Usage Total`
   - **State Template**:
     ```jinja
     {{ (states('sensor.s0pcm_reader_1_total') | float(0) / 1000) | round(3) }}
     ```
     *(Replace `sensor.s0pcm_reader_1_total` with your actual entity ID. Home Assistant typically prefixes the ID with the device name, resulting in `sensor.s0pcm_reader_<ID>_total` by default)*
   - **Unit of Measurement**: `m³` (for water) or `kWh` (for energy)
   - **Device Class**: `Water` or `Energy`
   - **State Class**: `Total increasing`
   - **Availability Template**:
     ```jinja
     {{ states('sensor.s0pcm_reader_1_total') | is_number }}
     ```
     *(This ensures the sensor doesn't show "0" or "Unknown" when the addon or MQTT is restarting)*
4. Click **Submit**.

> [!TIP]
> After creating the helper, you can immediately add it to your **Energy Dashboard** under **Settings** > **Dashboards** > **Energy**.

---

## Legacy / Manual Configuration (Optional)

> [!NOTE]
> This section is only for users who prefer manual configuration or are using older versions of Home Assistant.

If you are not using MQTT Discovery and stick to the default `mqtt_split_topic: true`, you can setup sensors manually in `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - state_topic: "s0pcmreader/1/total"
      name: "Water Totaal"
      unique_id: "water_totaal"
      value_template: "{{ value | float / 1000 }}"
      unit_of_measurement: m³
      state_class: total_increasing
      device_class: water
```

### Utility Meter Example
```yaml
utility_meter:
  daily_water:
    source: sensor.water_totaal
    cycle: daily
    name: Daily Water
```

### Heatpump Example (thanks to @wiljums for this)
```yaml
mqtt:
  sensor:
    - name: "Heatpump usage"
      state_topic: "s0pcmreader/1/total"
      value_template: "{{ value | float / 100 }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total
```