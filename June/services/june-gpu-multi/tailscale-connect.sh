#!/bin/bash
# Tailscale auto-connect script for june-gpu-multi service
# Uses direct userspace networking without SOCKS5 proxy (optimized)

set -e

echo "[TAILSCALE] Connecting to headscale network..."
echo "[TAILSCALE] Starting Tailscale connection to headscale.ozzu.world..."

# Check if required environment variables are set
if [ -z "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] ERROR: TAILSCALE_AUTH_KEY environment variable not set"
    exit 1
fi

# Create Tailscale directories if they don't exist
mkdir -p /var/lib/tailscale /var/run/tailscale

# Start tailscaled daemon with userspace networking (no proxy needed)
echo "[TAILSCALE] Starting Tailscale daemon..."
tailscaled \
    --state=/var/lib/tailscale/tailscaled.state \
    --socket=/var/run/tailscale/tailscaled.sock \
    --tun=userspace-networking &
TAILSCALED_PID=$!

# Wait for daemon to start
echo "[TAILSCALE] Waiting for daemon to initialize..."
sleep 8

# Connect to headscale with auth key using userspace mode
echo "[TAILSCALE] Connecting to headscale.ozzu.world..."
tailscale up \
    --login-server=https://headscale.ozzu.world \
    --authkey=$TAILSCALE_AUTH_KEY \
    --hostname=june-gpu-$(date +%s | tail -c 8) \
    --accept-routes \
    --accept-dns \
    --netfilter-mode=off

# Wait for connection to establish
echo "[TAILSCALE] Waiting for Tailscale connection..."
for i in {1..30}; do
    if tailscale status >/dev/null 2>&1; then
        echo "[TAILSCALE] Successfully connected to headscale network!"
        tailscale status
        break
    fi
    echo "[TAILSCALE] Attempt $i/30 - waiting for connection..."
    sleep 3
done

echo "[TAILSCALE] Direct Tailscale networking active - no proxy needed"

# Test direct connectivity to orchestrator service
echo "[TAILSCALE] Testing direct connectivity to orchestrator service..."
if curl -s --max-time 10 http://june-orchestrator:8080/healthz >/dev/null 2>&1; then
    echo "[TAILSCALE] ✅ Successfully connected to orchestrator via direct Tailscale networking!"
else
    echo "[TAILSCALE] ⚠️  Cannot reach orchestrator yet - service discovery may take a few moments"
fi

echo "[TAILSCALE] Tailscale userspace networking ready for direct service communication"

# Keep tailscaled running in foreground for supervisor
wait $TAILSCALED_PID