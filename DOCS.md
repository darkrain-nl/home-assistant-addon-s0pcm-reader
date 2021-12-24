# S0PCM Reader add-on documentation

## Configuration in Home Assistant

* Now you have the add-on sending data into MQTT you need to setup some sensors in Home Assistant manually via configuration.yaml
* How exactly really depends on your use case...
* An example for a single Water Meter can be found below:
```#S0PCM
sensor:
  - platform: mqtt
    state_topic: "s0pcmreader/1/total"
    name: "Water Totaal"
    unique_id: "water_totaal"
    value_template: "{{ value_json | float / 1000 }}"
    unit_of_measurement: m³
    icon: mdi:water-pump
    state_class: total_increasing
  - platform: mqtt
    state_topic: "s0pcmreader/1/today"
    name: "Water Vandaag"
    unique_id: "water_vandaag"
    unit_of_measurement: L
    icon: mdi:water-pump
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
