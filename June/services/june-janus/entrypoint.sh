#!/bin/bash
set -e

echo "=== Janus Custom Entrypoint ==="
echo "STUN_SERVER: ${STUN_SERVER}"
echo "TURN_SERVER: ${TURN_SERVER}"
echo "TURN_USERNAME: ${TURN_USERNAME}"

CONFIG_FILE="/usr/local/etc/janus/janus.jcfg"

if [ -f "$CONFIG_FILE" ]; then
    echo "Updating $CONFIG_FILE with TURN/STUN settings..."
    
    # Extract server and port from the environment variables
    STUN_HOST="${STUN_SERVER%:*}"
    STUN_PORT="${STUN_SERVER##*:}"
    TURN_HOST="${TURN_SERVER%:*}"
    TURN_PORT="${TURN_SERVER##*:}"
    
    # Uncomment and update STUN settings
    sed -i "s/#stun_server = \"stun.voip.eutelia.it\"/stun_server = \"$STUN_HOST\"/" "$CONFIG_FILE"
    sed -i "s/#stun_port = 3478/stun_port = $STUN_PORT/" "$CONFIG_FILE"
    
    # Uncomment and update TURN settings  
    sed -i "s/#turn_server = \"myturnserver.com\"/turn_server = \"$TURN_HOST\"/" "$CONFIG_FILE"
    sed -i "s/#turn_port = 3478/turn_port = $TURN_PORT/" "$CONFIG_FILE"
    sed -i "s/#turn_type = \"udp\"/turn_type = \"udp\"/" "$CONFIG_FILE"
    sed -i "s/#turn_user = \"myuser\"/turn_user = \"$TURN_USERNAME\"/" "$CONFIG_FILE"
    sed -i "s/#turn_pwd = \"mypassword\"/turn_pwd = \"$TURN_CREDENTIAL\"/" "$CONFIG_FILE"
    
    echo "Configuration updated successfully!"
    
    # Show the updated config
    echo "Updated STUN/TURN configuration:"
    grep -E "(stun_server|stun_port|turn_server|turn_port|turn_user|turn_pwd)" "$CONFIG_FILE"
    
else
    echo "ERROR: $CONFIG_FILE not found!"
    exit 1
fi

# Start nginx first, then Janus
echo "Starting nginx..."
nginx &

echo "Starting Janus..."
exec /usr/local/bin/janus
