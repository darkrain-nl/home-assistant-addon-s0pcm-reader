# S0PCM Reader App documentation

## MQTT Discovery

The app supports Home Assistant MQTT Discovery, which is **enabled by default**. This means you generally do **not** need to manually configure sensors in your `configuration.yaml` anymore.

When the app starts, it automatically creates a device named **S0PCM Reader** in Home Assistant with the following entities:

### Meter Entities (per enabled input)
These entities are replicated for every enabled input (e.g., 1, 2, 3...):
- **Total**: Total accumulated count.
- **Today**: Count for the current day.
- **Yesterday**: Count for the previous day.
- **Name**: Text configuration to rename the meter.
- **Total Correction**: Number configuration to set the total count.

### Device Sensors (global)
These sensors are unique and report on the app itself:
- **Status**: A binary sensor showing if the reader is connected to MQTT.
- **Error**: A diagnostic sensor that displays the last error encountered.
- **App Version**: Current version of the S0PCM Reader app.
- **S0PCM Firmware**: Firmware version reported by the hardware.
- **Startup Time**: Timestamp of when the app started.
- **Serial Port**: The configured USB/serial port.

### Naming Concept
The **Meter Entity** names and MQTT topics are determined by the configured **Meter Name**. If you haven't configured a name yet (e.g. via the _Name_ entity), it defaults to the numerical input ID (e.g., "1 Total"). 

> [!TIP]
> You can easily set or change these names via Home Assistant. See the **Naming Your Meters** section below for details.

> [!NOTE]
> **Historic Data**: Your historical data in Home Assistant is safely preserved even if you change the name of a meter. The app uses a stable `unique_id` based on the numerical input ID and the **MQTT Base Topic**, so Home Assistant will keep the data linked even if you rename "Meter 1" to "Water". Note that changing the base topic *will* break this link.

### Stateless Architecture (Storage & Persistence)

To protect your hardware (reduce SD card wear) and simplify management, this app is **stateless**. It does not use a local database file like `measurement.json` anymore. Instead, it leverages your **MQTT broker** and **Home Assistant** to store and recover your meter data.

#### How it works:
1. **Persistence**: Every time a pulse is counted, the app publishes the updated totals and internal state to your MQTT broker as **retained messages**.
2. **Recovery**: When the app starts, it automatically fetches its last known state from MQTT.
3. **Safety Net (HA API)**: If the MQTT broker has no data (e.g. it was just reset), the app automatically queries the **Home Assistant API** to recover the last known values from your sensors.

> [!NOTE]
> This app has fully migrated to a stateless architecture. Legacy `measurement.json` files are ignored and safe to delete.

## Configuration via Home Assistant UI

You can configure the following options directly in the **Settings > Apps > S0PCM Reader > Configuration** tab in Home Assistant:

### Required Settings
- **Device**: The serial port device (e.g., `/dev/ttyACM0`).
- **Recovery Wait Time**: Number of seconds to wait for MQTT messages on startup. Defaults to `7`. 
  > [!CAUTION]
  > Setting this value too low (e.g., `< 3s`) on slow hardware or busy networks can prevent the app from receiving all retained state data, potentially leading to **permanent data loss**. Do not change this unless you understand the implications.

### Optional Settings

> [!NOTE]
> Most optional settings are hidden by default for a cleaner interface. Click **"Show unused optional configuration options"** in the Home Assistant UI to reveal additional settings like MQTT host, port, protocol, discovery options, and more. All hidden settings have sensible defaults that work out-of-the-box.

#### General
- **Log Level**: The detail of the logs (debug, info, warning, error, critical). Defaults to `info`. Logs are streamed directly to the Home Assistant app console.

#### Connection Options
- **MQTT Host**: Manual host for an external broker. If not set, it uses the internally discovered broker (typically `core-mosquitto`).
- **MQTT Port**: The port for unencrypted MQTT. Defaults to `1883`.
- **MQTT Username**: Manual username for an external broker.
- **MQTT Password**: Manual password for an external broker.
- **MQTT Client ID**: Unique ID for the MQTT client. Defaults to auto-generated.
- **MQTT Base Topic**: The base topic for all MQTT messages. Defaults to `s0pcmreader`.
  > [!IMPORTANT]
  > Changing the base topic will change the **Unique ID** of the device in Home Assistant. This will cause Home Assistant to see it as a brand-new device, leaving your old sensors "Unavailable." Only change this if you are setting up a fresh installation or performing a controlled migration.
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
> All configuration is managed directly through the Home Assistant UI.

## Setting Meter Totals

You can update the total value of any meter (e.g., to sync with a physical meter) directly from the **Device** configuration page or via MQTT.

### Option 1: Via Home Assistant Device Page (Recommended)

1. Go to **Settings** > **Devices & Services** > **Devices**.
2. Search for **S0PCM Reader** (Integration: **MQTT**).
3. Under the **Configuration** section, look for the **Total Correction** entity for your meter (e.g., `number.1_total_correction`).
4. Enter the correct total value and click **Set**.

> [!NOTE]
> This will instantly update the internal counter and the `total` sensor. The maximum supported value is **2,147,483,647**.

### Option 2: Using Home Assistant Actions (Advanced)

1. Go to **Developer Tools** > **Actions**.
2. Search for **MQTT: Publish**.
3. Fill in the details:
   - **Topic**: `s0pcmreader/Water/total/set` (or use the ID: `s0pcmreader/1/total/set`)
   - **Payload**: `123456`
4. Click **Perform Action**.

> [!NOTE]
> You can use either the numerical **Meter ID** or your custom **Meter Name** (case-insensitive) in the topic. The app will automatically find the correct meter to update.

### Option 3: Using raw MQTT

Send an MQTT message to the following topic:
**Topic:** `<base_topic>/<name_or_id>/total/set`
**Payload:** The new integer value for the total.

> [!NOTE]
> You can use either the numerical **Meter ID** (1, 2, 3, etc.) or the custom **Meter Name** (if configured) in the set topic.

**Example:**
`mosquitto_pub -t "s0pcmreader/Water/total/set" -m "1000"`
or
`mosquitto_pub -t "s0pcmreader/1/total/set" -m "1000"`

> [!NOTE]
> This command only updates the **Total** counter. The **Today** and **Yesterday** counters remain unchanged and will continue to count based on the pulses received relative to the previous day's total.

## Naming Your Meters

Since measurement data is now stored in a private folder for better security and performance, you can no longer edit the data file manually. Instead, you can set (or change) meter names directly from the UI.

### Option 1: Via Home Assistant Device Page (Recommended)

1. Go to **Settings** > **Devices & Services** > **Devices**.
2. Search for **S0PCM Reader** (Integration: **MQTT**).
3. Under the **Configuration** section, look for the **Name** entity for your meter (e.g., `text.1_name`).
4. Type your desired name (e.g., `Kitchen`) and press **Enter**.

The app will immediately:
- Update the internal name.
- Update the `total`, `today`, and `yesterday` sensor names in Home Assistant.

### Option 2: Using Home Assistant Actions (Advanced)

1. Go to **Developer Tools** > **Actions**.
2. Search for **MQTT: Publish**.
3. Fill in the details:
   - **Topic**: `s0pcmreader/<ID>/name/set` (e.g., `s0pcmreader/1/name/set`)
   - **Payload**: `Kitchen` (or whatever you want to name it)
4. Click **Perform Action**.

### Option 3: Using raw MQTT

Send an MQTT message to the following topic:
**Topic:** `<base_topic>/<ID>/name/set`
**Payload:** Your desired meter name.

> [!TIP]
> To remove a name and revert to the default ID-based name, simply send an **empty payload** to the `name/set` topic.

The app will immediately:
- Update the internal name for that meter.
- Save the change permanently.
- Re-send MQTT Discovery messages to update the sensor names in Home Assistant.

## MQTT Error Reporting

The app monitors its internal operations and reports any issues to the `<base_topic>/error` topic. If MQTT Discovery is enabled, this will appear as an **Error** sensor in Home Assistant.

**Reported errors include:**
- **Serial Connection Failures:** If the S0PCM device is unplugged or the port is invalid.
- **MQTT Connection Issues:** If the broker is unreachable or the connection is lost (reported once reconnected).
- **Packet Parsing Issues:** If the data received from the S0PCM is corrupted or in an unknown format.
- **MQTT Command Errors:** If an invalid payload is sent to a `/total/set` topic.
- **Pulsecount Anomalies:** If a sudden jump or reset in pulse count is detected.
  - **S0PCM Reset (Warning):** If the device reads 0 (hardware restart), the app automatically recovers your totals and logs a Warning.
  - **Data Anomaly (Error):** If the pulse count drops unexpectedly but is not 0, a full Error is logged as this may indicate data corruption.


Once the issue is resolved and a valid data packet is successfully processed, the error sensor will automatically clear itself and display **"No Error"**.

## MQTT TLS Support

The app supports secure MQTT connections using TLS.

> [!WARNING]
> **Security Notice**: This app defaults to unencrypted MQTT for ease of setup with local brokers. If your MQTT broker is exposed to external networks or you want additional security, enable the **mqtt_tls** option in the **Configuration** tab.

- **Automatic Fallback:** If TLS connection fails (e.g., certificate error), the app will automatically fall back to a plain non-encrypted connection to ensure stable operation.
- **Port Swapping:** By default, the app uses **MQTT Port** for plain connections and **MQTT TLS Port** for encrypted connections.
- **Insecure by Default:** Certificate validation is disabled by default (`mqtt_tls_check_peer: false`) for compatibility with local brokers using self-signed certificates. To enable strict verification, set `mqtt_tls_check_peer` to `true`.
- **CA Certificate:** Provide the path to your CA certificate.
  - **Recommended:** Put your certificate in the Home Assistant `/ssl/` folder (accessible via Samba/SSH) and use the absolute path: `/ssl/your-ca.crt`.

## State Recovery & Data Safety

This app implements a multi-layered state recovery mechanism to ensure your totals are never lost, even without a local data file.

### Layer 1: MQTT Retained Messages (Primary)
The app publishes all internal states (totals, daily counts, and pulse counters) to MQTT with the `retain` flag. On startup, it waits for a set duration (**Recovery Wait Time**, default 7 seconds) to rebuild its internal memory from these messages.

> [!CAUTION]
> **Data Integrity Risk**: If you reduce the recovery wait time too much on slow hardware (like a Raspberry Pi 3), the app might start its main loop before the network has delivered all retained messages. This could result in the app incorrectly assuming a "zero" state for some meters, which would then be published to MQTT and override your previous totals. **Do not lower this value unless you are certain your network and hardware can handle near-instant delivery.**

### Layer 2: Home Assistant API (Secondary)
If MQTT recovery fails (e.g., the broker's database was cleared), the app will automatically query the **Home Assistant State API**. It fetches the last known value of your sensors (e.g., `sensor.s0pcm_s0pcmreader_1_total` with the default base topic) and uses them to resume counting.

> [!TIP]
> This dual-recovery system ensures that as long as either your MQTT broker or your Home Assistant instance has the data, the app will resume correctly.

> [!NOTE]
> **Recovery scope:** While Layer 1 (MQTT) recovers all statistics (today, yesterday, names, etc.), Layer 2 (HA API) is designed as a "surgical fallback" and only recovers **Lifetime Totals**. This ensures your long-term statistics and Energy Dashboard remain accurate even in a total MQTT wipeout.

> [!WARNING]
> **State Dependency Limitation**: If you wipe your MQTT broker and restart this app at the same time, the sensors in Home Assistant will likely show as **"Unavailable"**. In this state, Home Assistant cannot provide the numerical totals to the app, and recovery will fail. To avoid permanent data loss, **always back up your MQTT broker's database.**

> [!CAUTION]
> **Backup Advice**: While the recovery system is robust, it relies on external services. **Regularly back up your Home Assistant instance.** When performing a backup, ensure both the **S0PCM Reader** and your **MQTT broker** app are included.

### Testing the Recovery System

If you want to verify that the recovery system is working correctly, you can perform the following safe test:

1. Go to the **Configuration** tab of the app.
2. Change the **MQTT Base Topic** to a temporary name (e.g., `s0test`).
3. **Restart** the app.
4. Check the **Logs**. You should see the app searching MQTT, finding nothing, and then logging:
   `Recovery: Recovered total for meter 1 from HA API: <your_previous_total>`

By changing the topic, you effectively show the app a "blank slate" on MQTT, forcing it to use the secondary Layer 2 recovery from Home Assistant. Once verified, simply change the topic back to your original name.

> [!IMPORTANT]
> **Cleanup after testing:** Because Home Assistant uses the MQTT topic to uniquely identify the device, changing the topic for testing will create a **second device** in your Home Assistant dashboard. 
> 1. Once you revert to your original topic, the test device will show as "Unavailable."
> 2. You can then safely remove the test device by going to **Settings** > **Devices & Services** > **MQTT**, selecting the test device, and clicking **Delete**.

### Data Accuracy & App Downtime
The S0PCM hardware is a "live" counter. It does not store historical pulses while the app is stopped. Any pulses that occur while the app is not running will be lost by the software. 
To maintain perfect accuracy, you should occasionally check your physical meter's reading and sync it with the app using the **Setting Meter Totals** feature described above.

## Watchdog / Auto-restart

This app uses the [S6 Overlay][s6-overlay] for process supervision. If the S0PCM reader script crashes or exits unexpectedly, it will be automatically restarted.

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

The app **subscribes** to the following topics for control:

```
<base_topic>/<name_or_id>/total/set   (Payload: New total value)
<base_topic>/<name_or_id>/name/set    (Payload: New name string)
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
     {{ (states('sensor.s0pcm_s0pcmreader_1_total') | float(0) / 1000) | round(3) }}
     ```
     *(Replace `sensor.s0pcm_s0pcmreader_1_total` with your actual entity ID. The entity ID format is `sensor.s0pcm_<base_topic>_<meter_id>_total`, so with the default base topic `s0pcmreader`, meter 1's total is `sensor.s0pcm_s0pcmreader_1_total`)*
   - **Unit of Measurement**: `m³` (for water) or `kWh` (for energy)
   - **Device Class**: `Water` or `Energy`
   - **State Class**: `Total increasing`
   - **Availability Template**:
     ```jinja
     {{ states('sensor.s0pcm_s0pcmreader_1_total') | is_number }}
     ```
     *(This ensures the sensor doesn't show "0" or "Unknown" when the app or MQTT is restarting)*
4. Click **Submit**.

### Calculating Real-time Usage (Power/Flow)

Since the app only provides pulse counts, you can calculate the current usage (e.g. Watts for electricity or liters/min for water) using Home Assistant's **Derivative** or **Template** integrations.

#### Option A: Using the Derivative Helper (Recommended)
This is the easiest way to get a smooth usage value:
1. Go to **Settings** > **Devices & Services** > **Helpers**.
2. Click **+ Create Helper** and select **Derivative sensor**.
3. Select your **Template Sensor** (e.g., `Water Usage Total`) as the **Input sensor**.
4. Set **Precision** to `3`.
5. Set **Time window** to `00:01:00` (1 minute) for better smoothing.
6. Set **Unit prefix** to `None` and **Time unit** to `h` (hours) to get `m³/h`.

#### Option B: Using a Template (Advanced)
If you want to calculate the jump between individual pulses, you can use a template that compares the `last_changed` attribute, but the Derivative helper above is generally more robust for energy dashboard use cases.

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