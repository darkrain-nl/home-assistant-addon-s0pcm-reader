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
declare mqtt_tls="false"
declare mqtt_tls_ca=""
declare mqtt_tls_check_peer="false"
declare mqtt_tls_port="8883"


if ! bashio::fs.directory_exists "/share/s0pcm"; then
  mkdir /share/s0pcm || bashio::exit.nok "Could not create S0PCM data store."
fi

log_level=$(bashio::config 'log_level')
serial_port=$(bashio::config 'device')
mqtt_tls=$(bashio::config 'mqtt_tls')
mqtt_tls_ca=$(bashio::config 'mqtt_tls_ca')
mqtt_tls_check_peer=$(bashio::config 'mqtt_tls_check_peer')

# Service discovery overrides
if bashio::services.available "mqtt"; then
  mqtt_host=$(bashio::services "mqtt" "host")
  mqtt_password=$(bashio::services "mqtt" "password")
  mqtt_username=$(bashio::services "mqtt" "username")
  mqtt_port=$(bashio::services "mqtt" "port")
  mqtt_tls_port=$(bashio::services "mqtt" "tls_port")
fi

# Manual overrides from addon config
if bashio::config.has_value 'mqtt_port'; then
  mqtt_port=$(bashio::config 'mqtt_port')
fi

if bashio::config.has_value 'mqtt_tls_port'; then
  mqtt_tls_port=$(bashio::config 'mqtt_tls_port')
fi

# Generate config
bashio::var.json \
    serial_port "${serial_port}" \
    log_level "${log_level}" \
    mqtt_host "${mqtt_host}" \
    mqtt_password "${mqtt_password}" \
    mqtt_port "${mqtt_port}" \
    mqtt_username "${mqtt_username}" \
    mqtt_tls "${mqtt_tls}" \
    mqtt_tls_ca "${mqtt_tls_ca}" \
    mqtt_tls_check_peer "${mqtt_tls_check_peer}" \
    mqtt_tls_port "${mqtt_tls_port}" \
    | tempio \
        -template /usr/share/tempio/s0pcm_config.conf \
        -out /share/s0pcm/configuration.json