#!/usr/bin/with-contenv bashio
# ==============================================================================
# Generate S0PCM Reader config file
# ==============================================================================
declare log_level="warning"
declare mqtt_host="core-mosquitto"
declare mqtt_port="1883"
declare mqtt_username=""
declare mqtt_password=""
declare mqtt_client_id="None"
declare serial_port
declare mqtt_tls="false"
declare mqtt_tls_ca=""
declare mqtt_tls_check_peer="false"
declare mqtt_tls_port="8883"
declare mqtt_base_topic="s0pcmreader"
declare mqtt_protocol="5.0"
declare mqtt_discovery="true"
declare mqtt_discovery_prefix="homeassistant"
declare mqtt_retain="true"
declare mqtt_split_topic="true"


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
  
  # Only override defaults if values are provided by the service
  discovered_port=$(bashio::services "mqtt" "port")
  if [[ -n "${discovered_port}" && "${discovered_port}" != "null" ]]; then 
    mqtt_port="${discovered_port}"
  fi
fi

# Manual overrides from addon config
if bashio::config.has_value 'mqtt_host'; then
  mqtt_host=$(bashio::config 'mqtt_host')
fi

if bashio::config.has_value 'mqtt_username'; then
  mqtt_username=$(bashio::config 'mqtt_username')
fi

if bashio::config.has_value 'mqtt_password'; then
  mqtt_password=$(bashio::config 'mqtt_password')
fi

if bashio::config.has_value 'mqtt_client_id'; then
  mqtt_client_id=$(bashio::config 'mqtt_client_id')
fi

if bashio::config.has_value 'mqtt_base_topic'; then
  mqtt_base_topic=$(bashio::config 'mqtt_base_topic')
fi

if bashio::config.has_value 'mqtt_protocol'; then
  mqtt_protocol=$(bashio::config 'mqtt_protocol')
fi

if bashio::config.has_value 'mqtt_discovery'; then
  mqtt_discovery=$(bashio::config 'mqtt_discovery')
fi

if bashio::config.has_value 'mqtt_discovery_prefix'; then
  mqtt_discovery_prefix=$(bashio::config 'mqtt_discovery_prefix')
fi

if bashio::config.has_value 'mqtt_retain'; then
  mqtt_retain=$(bashio::config 'mqtt_retain')
fi

if bashio::config.has_value 'mqtt_split_topic'; then
  mqtt_split_topic=$(bashio::config 'mqtt_split_topic')
fi

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
    mqtt_client_id "${mqtt_client_id}" \
    mqtt_base_topic "${mqtt_base_topic}" \
    mqtt_protocol "${mqtt_protocol}" \
    mqtt_discovery "${mqtt_discovery}" \
    mqtt_discovery_prefix "${mqtt_discovery_prefix}" \
    mqtt_retain "${mqtt_retain}" \
    mqtt_split_topic "${mqtt_split_topic}" \
    mqtt_tls "${mqtt_tls}" \
    mqtt_tls_ca "${mqtt_tls_ca}" \
    mqtt_tls_check_peer "${mqtt_tls_check_peer}" \
    mqtt_tls_port "${mqtt_tls_port}" \
    | tempio \
        -template /usr/share/tempio/s0pcm_config.conf \
        -out /share/s0pcm/configuration.json