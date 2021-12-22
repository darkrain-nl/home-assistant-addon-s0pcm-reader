#!/usr/bin/with-contenv bashio
# ==============================================================================
# Generate S0PCM Reader config file
# ==============================================================================
declare log_level="warning"
#declare log_size
#declare log_count
declare mqtt_host="core-mosquitto"
declare mqtt_port="1883"
#declare mqtt_base_topic
declare mqtt_username=""
declare mqtt_password=""
#declare mqtt_client_id
#declare mqtt_retain
#declare mqtt_split_topic
#declare mqtt_tls
#declare mqtt_tls_ca
#declare mqtt_tls_check_peer
#declare mqtt_connect_retry
declare serial_port
#declare serial_baudrate
#declare serial_connect_retry
#declare serial_publish_interval
#declare serial_publish_onchange
#declare serial_include
#declare serial_dailystat

if bashio::fs.directory_exists "/data/config"; then
  bashio::exit.ok
fi

mkdir /data/config || bashio::exit.nok "Could not create config folder."

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
    mqtt_port "^${mqtt_port}" \
    mqtt_username "${mqtt_username}" \
    | tempio \
        -template /usr/share/tempio/s0pcm_config.conf \
        -out /data/config/configuration.json