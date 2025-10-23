#!/bin/bash

# Tailscale Userspace Networking Script
# For containers that don't have /dev/net/tun or privileged access

echo "[TAILSCALE] Starting Tailscale in userspace networking mode..."
echo "[TAILSCALE] Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Check required environment variables
if [ -z "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] ERROR: TAILSCALE_AUTH_KEY environment variable not set"
    exit 1
fi

if [ -z "$TAILSCALE_LOGIN_SERVER" ]; then
    echo "[TAILSCALE] WARNING: TAILSCALE_LOGIN_SERVER not set, using default Tailscale servers"
    LOGIN_SERVER_FLAG=""
else
    echo "[TAILSCALE] Using login server: $TAILSCALE_LOGIN_SERVER"
    LOGIN_SERVER_FLAG="--login-server=$TAILSCALE_LOGIN_SERVER"
fi

# Create Tailscale state directory
mkdir -p /var/lib/tailscale
mkdir -p /var/run/tailscale

echo "[TAILSCALE] Starting Tailscale daemon in userspace mode..."

# Start tailscaled in userspace mode with SOCKS5 and HTTP proxy
tailscaled \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --outbound-http-proxy-listen=localhost:1055 \
    --state=/var/lib/tailscale/tailscaled.state \
    --socket=/var/run/tailscale/tailscaled.sock &

# Wait for daemon to start
echo "[TAILSCALE] Waiting for daemon to initialize..."
sleep 5

# Authenticate with Tailscale/Headscale
echo "[TAILSCALE] Authenticating with auth key..."
if [ -n "$LOGIN_SERVER_FLAG" ]; then
    tailscale up $LOGIN_SERVER_FLAG --authkey="$TAILSCALE_AUTH_KEY" --accept-routes
else
    tailscale up --authkey="$TAILSCALE_AUTH_KEY" --accept-routes
fi

# Check connection status
echo "[TAILSCALE] Checking connection status..."
sleep 3
tailscale status

# Test connectivity if we have a test endpoint
if [ -n "$TAILSCALE_TEST_ENDPOINT" ]; then
    echo "[TAILSCALE] Testing connectivity to $TAILSCALE_TEST_ENDPOINT..."
    ALL_PROXY=socks5://localhost:1055/ curl -m 10 "$TAILSCALE_TEST_ENDPOINT" && \
        echo "[TAILSCALE] OK Connectivity test successful!" || \
        echo "[TAILSCALE] FAIL Connectivity test failed"
fi

echo "[TAILSCALE] Userspace networking setup complete"
echo "[TAILSCALE] SOCKS5 proxy available at: localhost:1055"
echo "[TAILSCALE] HTTP proxy available at: localhost:1055"
echo "[TAILSCALE] To use proxy, set: export ALL_PROXY=socks5://localhost:1055/"
echo "[TAILSCALE] Or set: export HTTP_PROXY=http://localhost:1055/"
