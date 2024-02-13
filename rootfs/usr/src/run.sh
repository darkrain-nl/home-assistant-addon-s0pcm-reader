#!/usr/bin/env bashio
set -e
declare s0pcm_version

# Copy example configuration if not exists
if [ ! -f /share/s0pcm/configuration.json ]; then
  cp /usr/src/configuration.json.example /share/s0pcm/configuration.json
fi

s0pcm_version = bashio::addon.version
bashio::log.info "Starting S0PCm Reader... version ${s0pcm_version}"

python /usr/src/s0pcm-reader.py -c /share/s0pcm

if [ -f /share/s0pcm/.noexit ]; then
  sleep 7d
fi
