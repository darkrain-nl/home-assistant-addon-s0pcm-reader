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