# S0PCM Reader add-on documentation

## MQTT Discovery

The add-on supports Home Assistant MQTT Discovery, which is **enabled by default**. This means you generally do **not** need to manually configure sensors in your `configuration.yaml` anymore.

When the add-on starts, it automatically creates a device named **S0PCM Reader** in Home Assistant with the following sensors for each enabled input:
-   **Total**: Total accumulated count.
-   **Today**: Count for the current day.
-   **Yesterday**: Count for the previous day.

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