#!/bin/bash
set -e

echo "=== Janus Custom Entrypoint ==="
echo "STUN_SERVER: ${STUN_SERVER}"
echo "TURN_SERVER: ${TURN_SERVER}"
echo "TURN_USERNAME: ${TURN_USERNAME}"

# Replace placeholders in config file
if [ -f "/opt/janus/etc/janus/janus.jcfg" ]; then
    echo "Updating janus.jcfg with TURN/STUN settings..."
    sed -i "s/STUN_SERVER_PLACEHOLDER/${STUN_SERVER}/g" /opt/janus/etc/janus/janus.jcfg
    sed -i "s/TURN_SERVER_PLACEHOLDER/${TURN_SERVER}/g" /opt/janus/etc/janus/janus.jcfg
    sed -i "s/TURN_USERNAME_PLACEHOLDER/${TURN_USERNAME}/g" /opt/janus/etc/janus/janus.jcfg
    sed -i "s/TURN_CREDENTIAL_PLACEHOLDER/${TURN_CREDENTIAL}/g" /opt/janus/etc/janus/janus.jcfg
    echo "Configuration updated successfully!"
else
    echo "WARNING: janus.jcfg not found, using defaults"
fi

# Start nginx first (as in original), then Janus
echo "Starting nginx..."
nginx &

echo "Starting Janus..."
exec /usr/local/bin/janus
