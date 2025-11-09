#!/usr/bin/with-contenv bashio
# ==============================================================================
# Generate S0PCM Reader config file
# ==============================================================================
declare log_level="warning"
declare mqtt_host="core-mosquitto"
declare mqtt_port="1883"
declare mqtt_username=""
declare mqtt_password=""
declare serial_port


if ! bashio::fs.directory_exists "/share/s0pcm"; then
  mkdir /share/s0pcm || bashio::exit.nok "Could not create S0PCM data store."
fi

log_level=$(bashio::config 'log_level')
serial_port=$(bashio::config 'device')

if bashio::services.available "mqtt"; then
  mqtt_host=$(bashio::services "mqtt" "host")
  mqtt_password=$(bashio::services "mqtt" "password")
  mqtt_port=$(bashio::services "mqtt" "port")
  mqtt_username=$(bashio::services "mqtt" "username")
fi

# Generate config
bashio::var.json \
    serial_port "${serial_port}" \
    log_level "${log_level}" \
    mqtt_host "${mqtt_host}" \
    mqtt_password "${mqtt_password}" \
    mqtt_port "${mqtt_port}" \
    mqtt_username "${mqtt_username}" \
    | tempio \
        -template /usr/share/tempio/s0pcm_config.conf \
        -out /share/s0pcm/configuration.json