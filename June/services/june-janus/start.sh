#!/bin/bash
set -e

# Update library paths
export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH"
ldconfig

# Create necessary directories
mkdir -p /opt/janus/var/log
mkdir -p /opt/janus/var/run

# Copy Janus configuration if provided
if [ -d "/app/janus-config" ]; then
    cp -r /app/janus-config/* /opt/janus/etc/janus/ 2>/dev/null || true
fi

# Set default config if none exists
if [ ! -f "/opt/janus/etc/janus/janus.jcfg" ]; then
    cat > /opt/janus/etc/janus/janus.jcfg << EOF
general: {
    configs_folder = "/opt/janus/etc/janus"
    plugins_folder = "/opt/janus/lib/janus/plugins"
    transports_folder = "/opt/janus/lib/janus/transports"
    events_folder = "/opt/janus/lib/janus/events"
    loggers_folder = "/opt/janus/lib/janus/loggers"
    
    debug_level = 4
    debug_timestamps = true
    debug_colors = false
    
    interface = "0.0.0.0"
    
    api_secret = "${JANUS_API_SECRET:-janussecret}"
    admin_secret = "${JANUS_ADMIN_KEY:-janusoverlord}"
    
    server_name = "Janus WebRTC Server"
    session_timeout = 60
    candidates_timeout = 45
    
    rtp_port_range = "20000-40000"
}
EOF
fi

# Configure HTTP transport
if [ ! -f "/opt/janus/etc/janus/janus.transport.http.jcfg" ]; then
    cat > /opt/janus/etc/janus/janus.transport.http.jcfg << EOF
general: {
    json = "indented"
    base_path = "/janus"
    http = true
    port = 8088
    interface = "0.0.0.0"
    
    admin_base_path = "/admin"
    admin_http = true
    admin_port = 7088
    admin_interface = "0.0.0.0"
}
EOF
fi

# Configure WebSocket transport
if [ ! -f "/opt/janus/etc/janus/janus.transport.websockets.jcfg" ]; then
    cat > /opt/janus/etc/janus/janus.transport.websockets.jcfg << EOF
general: {
    json = "indented"
    ws = true
    ws_port = 8188
    ws_interface = "0.0.0.0"
    
    admin_ws = true
    admin_ws_port = 7188
    admin_ws_interface = "0.0.0.0"
}
EOF
fi

# Start health check server in background (if you need it)
if [ -f "/app/health_server.py" ]; then
    echo "Starting health check server..."
    python3 /app/health_server.py &
fi

# Start Janus Gateway (main process)
echo "Starting Janus WebRTC Gateway..."
exec /opt/janus/bin/janus \
    --configs-folder=/opt/janus/etc/janus \
    --log-file=/opt/janus/var/log/janus.log \
    --interface=0.0.0.0 \
    --debug-level=4 \
    --stun-server=stun.l.google.com:19302
