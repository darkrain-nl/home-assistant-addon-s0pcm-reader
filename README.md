# home-assistant-addon-s0pcm-reader

![Reported Installations][installations-shield-stable]

Based on the work of @ualex73 (https://github.com/ualex73/docker-s0pcm-reader) if you cannot run Home Assistant Add-ons maybe his docker is a nice alternative.

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

[installations-shield-stable]: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Faddons.json&query=%24%5B%224a252ed0_s0pcm_reader%22%5D.total&label=Reported%20Installations&link=https%3A%2F%2Fanalytics.home-assistant.io/add-ons