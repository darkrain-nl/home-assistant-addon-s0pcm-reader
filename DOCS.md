# S0PCM Reader add-on documentation

## MQTT Discovery

The add-on supports Home Assistant MQTT Discovery, which is **enabled by default**. This means you generally do **not** need to manually configure sensors in your `configuration.yaml` anymore.

When the add-on starts, it automatically creates a device named **S0PCM Reader** in Home Assistant with the following sensors for each enabled input:
-   **Total**: Total accumulated count.
-   **Today**: Count for the current day.
-   **Yesterday**: Count for the previous day.
-   **Status**: A binary sensor showing if the reader is connected to MQTT (connectivity class).

**Naming:**
The entity names are derived from the `name` field in your `measurement.yaml`. If you haven't configured a name, it defaults to the input number (e.g., "1 Total").

## Manual Configuration (Legacy / Optional)

* Now you have the add-on sending data into MQTT you need to setup some sensors in Home Assistant manually via configuration.yaml
* How exactly really depends on your use case...
* An example for a single Water Meter can be found below:

```
# S0PCM

mqtt:
  sensor:
    - state_topic: "s0pcmreader/1/total"
      name: "Water Totaal"
      unique_id: "water_totaal"
      value_template: "{{ value_json | float / 1000 }}"
      unit_of_measurement: m³
      icon: mdi:water-pump
      state_class: total_increasing
      device_class: water
    - state_topic: "s0pcmreader/1/total"
      name: "Waterquantity"
      unique_id: "water_quantity"
      unit_of_measurement: l
      icon: mdi:water-pump
      state_class: total_increasing
    - state_topic: "s0pcmreader/1/today"
      name: "Water Vandaag"
      unique_id: "water_vandaag"
      unit_of_measurement: l
      icon: mdi:water-pump

# Utility meter, for hourly, daily and montlhy values

utility_meter:
  hourly_water:
    source: sensor.waterquantity
    cycle: hourly
    name: Hourly Water
  daily_water:
    source: sensor.waterquantity
    cycle: daily
    name: Daily Water
  monthly_water:
    source: sensor.waterquantity
    cycle: monthly
    name: Monthly Water

```
## MQTT Message
The following MQTT messages are send:

```
<s0pcmreader>/1/total
<s0pcmreader>/1/today
<s0pcmreader>/1/yesterday
<s0pcmreader>/2/total
<s0pcmreader>/2/today
<s0pcmreader>/2/yesterday
<s0pcmreader>/X/total
<s0pcmreader>/X/today
<s0pcmreader>/X/yesterday
```

## Another example, this is for a heatpump (thanks to @wiljums for this)

```
mqtt:
  sensor:
    - name: "Heatpump usage"
      state_topic: "s0pcmreader/1/total"
      unique_id: "heatpump_usage"
      value_template: "{{ value_json | float / 100 }}"
      unit_of_measurement: kWh
      icon: mdi:water-pump
      device_class: energy
      state_class: total
    - name: "Heatpump vandaag"
      state_topic: "s0pcmreader/1/today"
      unique_id: "heatpump_vandaag"
      value_template: "{{ value_json | float * 10 }}"
      unit_of_measurement: Wh
      icon: mdi:water-pump

sensor:  
  platform: derivative
  source: sensor.heatpump_vandaag
  name: 'Warmtepomp verbruik (W)'
  unit: W
  unit_time: h

```

## Watchdog / Auto-restart

This add-on uses the [S6 Overlay](https://github.com/just-containers/s6-overlay) for process supervision. This means if the S0PCM reader script crashes or exits unexpectedly, it will be automatically restarted by the supervisor.

If you see repeated restarts in the logs, check the log output for errors from the python script.

## Resetting / Setting Meter Totals via MQTT

You can update the total value of any meter (e.g., to sync with a physical meter) by sending an MQTT message.

**Topic:**
`<base_topic>/<meter_id>/total/set`

**Payload:**
The new integer value for the total.

**Example:**
To set meter 1 total to 1000:
`mosquitto_pub -t "s0pcmreader/1/total/set" -m "1000"`

This will immediately update the internal counter and the `measurement.yaml` file.

## Setting Meter Totals using Home Assistant

To set the meter total using Home Assistant directly:

1.  Go to **Developer Tools** > **Actions**.
2.  Search for **MQTT: Publish**.
3.  Fill in the details:
    *   **Topic**: `s0pcmreader/1/total/set` (adjust base topic and meter ID as needed)
    *   **Payload**: `123456` (your new total value)
    *   **QoS**: `0` or `1`
    *   **Retain**: `Disabled`
4.  Click **Perform Action**.

> **Note:** This command only updates the **Total** counter. The **Today** and **Yesterday** counters remain unchanged and will continue to count based on the pulses received relative to the previous day's total.

## MQTT TLS Support

The add-on supports secure MQTT connections using TLS.

- **Automatic Fallback:** If TLS connection fails (e.g., certificate error or broker not supporting TLS on that port), the add-on will automatically fall back to a plain non-encrypted connection to ensure "rock stable" operation.
- **Port Swapping:** By default, the addon uses **MQTT Port** for plain connections and **MQTT TLS Port** for encrypted connections. If it falls back, it also switches to the non-TLS port.
- **Insecure by Default:** By default, certificate validation and hostname checking are disabled (`tls_check_peer: false`). This is to ensure compatibility with many local MQTT brokers using self-signed certificates.
- **CA Certificate:** If you want to use a specific CA certificate, you can provide the path in **MQTT TLS CA**.
    - **Relative path:** If you enter just a filename (e.g., `ca.crt`), the addon will look for it in `/share/s0pcm/ca.crt`.
    - **Absolute path:** You can also use an absolute path to a file elsewhere, such as `/ssl/mosquitto.crt`.

## Configuration via Home Assistant UI

You can configure the following options directly in the **Settings > Add-ons > S0PCM Reader > Configuration** tab in Home Assistant:

- **Device**: The serial port device (e.g., `/dev/ttyACM0`).
- **Log Level**: The detail of the logs (debug, info, warning, error, critical).
- **MQTT Port**: The port for unencrypted MQTT (defaults to `1883`).
- **MQTT TLS Port**: The port for encrypted MQTT (defaults to `8883`).
- **MQTT TLS**: Enable or disable TLS for MQTT (defaults to `false`).
- **MQTT TLS CA**: Filename or full path to your CA certificate.
    - *Example (Relative):* `ca.crt` (placed in `/share/s0pcm/`)
    - *Example (Absolute):* `/ssl/ca.crt`
- **MQTT TLS Check Peer**: Enable or disable certificate and hostname verification (defaults to `false`).

> **Note:** If these options are set in the Home Assistant UI, they will override any corresponding settings in your `configuration.json` file.