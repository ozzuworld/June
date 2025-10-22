#!/bin/bash
# Tailscale auto-connect script for june-gpu-multi service
# Connects to headscale.ozzu.world VPN automatically

set -e

echo "[TAILSCALE] Starting Tailscale connection to headscale.ozzu.world..."

# Check if required environment variables are set
if [ -z "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] ERROR: TAILSCALE_AUTH_KEY environment variable not set"
    exit 1
fi

# Start tailscaled daemon in background
echo "[TAILSCALE] Starting Tailscale daemon..."
tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &
TAILSCALED_PID=$!

# Wait for daemon to start
sleep 5

# Connect to headscale with auth key
echo "[TAILSCALE] Connecting to headscale.ozzu.world..."
tailscale up \
    --login-server=https://headscale.ozzu.world \
    --authkey=$TAILSCALE_AUTH_KEY \
    --hostname=june-gpu-$(hostname | cut -c1-8) \
    --accept-routes \
    --accept-dns

# Wait for connection to establish
echo "[TAILSCALE] Waiting for Tailscale connection..."
for i in {1..30}; do
    if tailscale status >/dev/null 2>&1; then
        echo "[TAILSCALE] Successfully connected to headscale network!"
        tailscale status
        break
    fi
    echo "[TAILSCALE] Attempt $i/30 - waiting for connection..."
    sleep 2
done

# Verify connectivity to orchestrator
echo "[TAILSCALE] Testing connectivity to orchestrator service..."
if curl -s --max-time 10 http://june-orchestrator:8080/healthz >/dev/null 2>&1; then
    echo "[TAILSCALE] ✅ Successfully connected to orchestrator via Tailscale!"
else
    echo "[TAILSCALE] ⚠️  Cannot reach orchestrator yet - will retry during service startup"
fi

# Keep tailscaled running
wait $TAILSCALED_PID