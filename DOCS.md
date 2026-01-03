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
The entity names are derived from the `name` field in your `measurement.yaml`. If you haven't configured a name, it defaults to the input number (e.g., "1 Total").

## Configuration via Home Assistant UI

You can configure the following options directly in the **Settings > Add-ons > S0PCM Reader > Configuration** tab in Home Assistant:

- **Device**: The serial port device (e.g., `/dev/ttyACM0`).
- **Log Level**: The detail of the logs (debug, info, warning, error, critical).
- **MQTT Host**: (Optional) Manual host for an external broker. If not set, it uses the internally discovered broker.
- **MQTT Port**: (Optional) The port for unencrypted MQTT (defaults to `1883`).
- **MQTT Username**: (Optional) Manual username for an external broker.
- **MQTT Password**: (Optional) Manual password for an external broker.
- **MQTT Client ID**: (Optional) Unique ID for the MQTT client.
- **MQTT Base Topic**: (Optional) The base topic for all MQTT messages (defaults to `s0pcmreader`).
- **MQTT Discovery**: (Optional) Enable or disable Home Assistant auto-discovery (defaults to `true`).
- **MQTT TLS**: Enable or disable TLS for MQTT (defaults to `false`).
- **MQTT TLS Port**: (Optional) The port for encrypted MQTT (defaults to `8883`).
- **MQTT TLS CA**: Filename or full path to your CA certificate.
- **MQTT TLS Check Peer**: Enable or disable certificate and hostname verification (defaults to `false`).

> **Note:** If these options are set in the Home Assistant UI, they will override any corresponding settings in your `configuration.json` file.

## Setting Meter Totals

You can update the total value of any meter (e.g., to sync with a physical meter) using either MQTT or the Home Assistant UI.

### Option 1: Using Home Assistant Actions (Recommended)

1. Go to **Developer Tools** > **Actions**.
2. Search for **MQTT: Publish**.
3. Fill in the details:
   - **Topic**: `s0pcmreader/1/total/set` (adjust base topic and meter ID as needed)
   - **Payload**: `123456` (your new total value)
   - **QoS**: `0` or `1`
   - **Retain**: `Disabled`
4. Click **Perform Action**.

### Option 2: Using raw MQTT

Send an MQTT message to the following topic:
**Topic:** `<base_topic>/<meter_id>/total/set`
**Payload:** The new integer value for the total.

**Example:**
`mosquitto_pub -t "s0pcmreader/1/total/set" -m "1000"`

> **Note:** This command only updates the **Total** counter. The **Today** and **Yesterday** counters remain unchanged and will continue to count based on the pulses received relative to the previous day's total.

## MQTT Error Reporting

The add-on monitors its internal operations and reports any issues to the `<base_topic>/error` topic. If MQTT Discovery is enabled, this will appear as an **Error** sensor in Home Assistant.

**Reported errors include:**
- **Serial Connection Failures:** If the S0PCM device is unplugged or the port is invalid.
- **MQTT Connection Issues:** If the broker is unreachable or the connection is lost (reported once reconnected).
- **Packet Parsing Issues:** If the data received from the S0PCM is corrupted or in an unknown format.
- **MQTT Command Errors:** If an invalid payload is sent to a `/total/set` topic.
- **Pulsecount Anomalies:** If a sudden jump or reset in pulse count is detected (e.g., after an S0PCM restart).

Once the issue is resolved and a valid data packet is successfully processed, the error sensor will automatically clear itself (it will become empty).

## MQTT TLS Support

The add-on supports secure MQTT connections using TLS.

- **Automatic Fallback:** If TLS connection fails (e.g., certificate error), the add-on will automatically fall back to a plain non-encrypted connection to ensure stable operation.
- **Port Swapping:** By default, the addon uses **MQTT Port** for plain connections and **MQTT TLS Port** for encrypted connections.
- **Insecure by Default:** Certificate validation is disabled by default (`tls_check_peer: false`) for compatibility with local brokers using self-signed certificates.
- **CA Certificate:** Provide the path in **MQTT TLS CA**.
  - **Relative path:** `ca.crt` (looked for in `/share/s0pcm/ca.crt`).
  - **Absolute path:** e.g., `/ssl/mosquitto.crt`.

## Watchdog / Auto-restart

This add-on uses the [S6 Overlay](https://github.com/just-containers/s6-overlay) for process supervision. If the S0PCM reader script crashes or exits unexpectedly, it will be automatically restarted.

## MQTT Message Details

The following MQTT messages are sent:

```
<base_topic>/1/total
<base_topic>/1/today
<base_topic>/X/total
<base_topic>/status
<base_topic>/error
<base_topic>/version
<base_topic>/firmware
<base_topic>/startup_time
<base_topic>/port
```

If `mqtt_split_topic` is set to `false`, the data is sent as a JSON string:
`base_topic/1` -> `{"total": 12345, "today": 15, "yesterday": 77}`

---

## Legacy / Manual Configuration (Optional)

> [!NOTE]
> This section is only for users who prefer manual configuration or are using older versions of Home Assistant.

If you are not using MQTT Discovery, you can setup sensors manually in `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - state_topic: "s0pcmreader/1/total"
      name: "Water Totaal"
      unique_id: "water_totaal"
      value_template: "{{ value_json | float / 1000 }}"
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
      value_template: "{{ value_json | float / 100 }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total
```