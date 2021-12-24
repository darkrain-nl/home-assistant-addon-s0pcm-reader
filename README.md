# home-assistant-addon-s0pcm-reader

Please be aware this Add-on is work in progress and may not yet do what you expect from it.

If you understand this and want to help test it, great! If you don't want any hassle then please wait till it is a bit more user friendly.

## Prerequisites
- You need an S0PCM reader (either S0PCM-2 or S0PCM-5)
- The Mosquitto broker add-on needs to be installed

## Installation instructions

* Add this repository to the Add-on repositories in Home Assistant
* Click reload
* Install the Add-on
* Do the minimal needed configuration by selecting the S0PCM USB device
* At this stage it might be a good idea to set the log level to Debug
* Start the Add-on and observe the log tab
* 3 files are now created in /share/s0pcm
* If you want to have correct totals you can add them to the measurement.yaml file
* Restart the add-on for the new totals to be used

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
