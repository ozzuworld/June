#!/bin/bash
set -e

echo "=== Janus Custom Entrypoint ==="
echo "STUN_SERVER: ${STUN_SERVER}"
echo "TURN_SERVER: ${TURN_SERVER}"  
echo "TURN_USERNAME: ${TURN_USERNAME}"

# Determine the correct config file path based on the base image
CONFIG_FILE_1="/usr/local/etc/janus/janus.jcfg"
CONFIG_FILE_2="/opt/janus/etc/janus/janus.jcfg"

if [ -f "$CONFIG_FILE_1" ]; then
    CONFIG_FILE="$CONFIG_FILE_1"
elif [ -f "$CONFIG_FILE_2" ]; then
    CONFIG_FILE="$CONFIG_FILE_2"
else
    echo "ERROR: Could not find janus.jcfg in standard locations!"
    exit 1
fi

echo "Using config file: $CONFIG_FILE"

if [ -f "$CONFIG_FILE" ]; then
    echo "Updating $CONFIG_FILE with TURN/STUN settings..."
    
    # Extract server and port from the environment variables
    STUN_HOST="${STUN_SERVER%:*}"
    STUN_PORT="${STUN_SERVER##*:}"
    TURN_HOST="${TURN_SERVER%:*}"
    TURN_PORT="${TURN_SERVER##*:}"
    
    echo "Parsed STUN: ${STUN_HOST}:${STUN_PORT}"
    echo "Parsed TURN: ${TURN_HOST}:${TURN_PORT}"
    
    # Create a backup first
    cp "$CONFIG_FILE" "${CONFIG_FILE}.backup"
    
    # Update STUN settings - handle both commented and placeholder versions
    sed -i "s/#stun_server = \"stun.voip.eutelia.it\"/stun_server = \"$STUN_HOST\"/" "$CONFIG_FILE"
    sed -i "s/#stun_port = 3478/stun_port = $STUN_PORT/" "$CONFIG_FILE"
    sed -i "s/stun_server = \"STUN_SERVER_PLACEHOLDER\"/stun_server = \"$STUN_HOST\"/" "$CONFIG_FILE"
    
    # Update TURN settings
    sed -i "s/#turn_server = \"myturnserver.com\"/turn_server = \"$TURN_HOST\"/" "$CONFIG_FILE"
    sed -i "s/#turn_port = 3478/turn_port = $TURN_PORT/" "$CONFIG_FILE"
    sed -i "s/#turn_type = \"udp\"/turn_type = \"udp\"/" "$CONFIG_FILE"
    sed -i "s/#turn_user = \"myuser\"/turn_user = \"$TURN_USERNAME\"/" "$CONFIG_FILE"
    sed -i "s/#turn_pwd = \"mypassword\"/turn_pwd = \"$TURN_CREDENTIAL\"/" "$CONFIG_FILE"
    
    # Handle placeholder versions too
    sed -i "s/t
