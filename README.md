# home-assistant-addon-s0pcm-reader

Please be aware this Add-on is work in progress and may not yet do what you expect from it.

If you understand this and want to help test it, great! If you don't want any hassle then please wait till it is a bit more user friendly.

* Add this repository to the Add-on repositories in Home Assistant
* Click reload
* Install the Add-on
* Do the minimal needed configuration by selecting the S0PCM USB device
* At this stage it might be smart to set the log level to Debug
* Start the Add-on and observe the log tab
* 3 files are now created in /share/s0pcm
* IF you want to have correct totals you can add then to the measurement.yaml file
* Restart the add-on for the new totals to be used

The configuration.json and measurement.yaml files will be store in /share/s0pcm on your Home Assistant OS.
You can edit measurement.yaml to enter the current meter readings, they will then be used in the add-on after a restart.
