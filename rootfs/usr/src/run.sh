#!/usr/bin/env bashio
set -e

# Copy example configuration if not exists
if [ ! -f /share/s0pcm/configuration.json ]; then
  cp /usr/src/configuration.json.example /share/s0pcm/configuration.json
fi

echo "${SUPERVISOR_TOKEN}"

VERSION=$(bashio::addon.version)
echo "ADDON VERSION: ${VERSION}"
UPDATEAVAIL=$(bashio::addon.update_available)
echo "ADDON UPDATE AVAILABLE: ${UPDATEAVAIL}"

python /usr/src/s0pcm-reader.py -c /share/s0pcm

if [ -f /share/s0pcm/.noexit ]; then
  sleep 7d
fi
