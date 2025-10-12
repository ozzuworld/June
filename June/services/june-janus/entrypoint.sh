#!/bin/bash
set -e

echo "=== Janus Custom Entrypoint ==="
echo "STUN_SERVER: ${STUN_SERVER}"
echo "TURN_SERVER: ${TURN_SERVER}"
echo "TURN_USERNAME: ${TURN_USERNAME}"

# Update the config file that Janus actually reads
CONFIG_FILE="/usr/local/etc/janus/janus.jcfg"

if [ -f "$CONFIG_FILE" ]; then
    echo "Updating $CONFIG_FILE with TURN/STUN settings..."
    
    # Enable and configure STUN server
    sed -i 's/#stun_server = "stun.voip.eutelia.it"/stun_server = "'${STUN_SERVER}'"/' "$CONFIG_FILE"
    sed -i 's/#stun_port = 3478/stun_port = 3478/' "$CONFIG_FILE"
    
    # Add TURN configuration (insert after stun_port line)
    sed -i '/stun_port = 3478/a\\tturn_server = "'${TURN_SERVER}'"\n\tturn_port = 3478\n\tturn_type = "udp"\n\tturn_user = "'${TURN_USERNAME}'"\n\tturn_pwd = "'${TURN_CREDENTIAL}'"' "$CONFIG_FILE"
    
    echo "Configuration updated successfully!"
    
    # Show the updated nat section for verification
    echo "Updated nat configuration:"
    sed -n '/nat: {/,/}/p' "$CONFIG_FILE"
else
    echo "ERROR: $CONFIG_FILE not found!"
    exit 1
fi

# Start nginx first, then Janus
echo "Starting nginx..."
nginx &

echo "Starting Janus..."
exec /usr/local/bin/janus
