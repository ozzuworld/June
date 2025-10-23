#!/bin/bash
# Tailscale auto-connect script for june-gpu-multi service
# Uses userspace networking mode for container compatibility

set -e

echo "[TAILSCALE] Starting Tailscale in userspace networking mode..."

# Check if required environment variables are set
if [ -z "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] ERROR: TAILSCALE_AUTH_KEY environment variable not set"
    exit 1
fi

# Create Tailscale directories if they don't exist
mkdir -p /var/lib/tailscale /var/run/tailscale

# Start tailscaled daemon with userspace networking mode
echo "[TAILSCALE] Starting Tailscale daemon with userspace networking..."
tailscaled \
    --state=/var/lib/tailscale/tailscaled.state \
    --socket=/var/run/tailscale/tailscaled.sock \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --outbound-http-proxy-listen=localhost:1055 &
TAILSCALED_PID=$!

# Wait for daemon to start
echo "[TAILSCALE] Waiting for daemon to initialize..."
sleep 8

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
    sleep 3
done

# Set proxy environment variables for applications
echo "[TAILSCALE] Setting up proxy environment..."
export ALL_PROXY=socks5://localhost:1055/
export HTTP_PROXY=http://localhost:1055/
export http_proxy=http://localhost:1055/
export HTTPS_PROXY=http://localhost:1055/
export https_proxy=http://localhost:1055/

# Save proxy settings to a file for other processes
cat > /etc/environment << EOF
ALL_PROXY=socks5://localhost:1055/
HTTP_PROXY=http://localhost:1055/
http_proxy=http://localhost:1055/
HTTPS_PROXY=http://localhost:1055/
https_proxy=http://localhost:1055/
EOF

echo "[TAILSCALE] Proxy configuration saved to /etc/environment"

# Test connectivity through proxy (using curl with proxy)
echo "[TAILSCALE] Testing connectivity to orchestrator service..."
if curl -s --max-time 10 --proxy socks5://localhost:1055 http://june-orchestrator:8080/healthz >/dev/null 2>&1; then
    echo "[TAILSCALE] ✅ Successfully connected to orchestrator via Tailscale!"
elif curl -s --max-time 10 --proxy http://localhost:1055 http://june-orchestrator:8080/healthz >/dev/null 2>&1; then
    echo "[TAILSCALE] ✅ Successfully connected to orchestrator via HTTP proxy!"
else
    echo "[TAILSCALE] ⚠️  Cannot reach orchestrator yet - services will use proxy when available"
fi

echo "[TAILSCALE] Tailscale userspace networking active with proxies on localhost:1055"

# Keep tailscaled running
wait $TAILSCALED_PID