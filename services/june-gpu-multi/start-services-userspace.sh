#!/bin/bash

# Enhanced June GPU Multi-Service Container Startup Script
# With Tailscale Userspace Networking Support

set -e

echo "[INIT] Starting June GPU Multi-Service Container with Tailscale Userspace"
echo "[INIT] Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# GPU Detection
echo "[INIT] GPU Detection:"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,uuid --format=csv,noheader,nounits | sed 's/^/GPU /g' | nl -v0 -s': '
else
    echo "No NVIDIA GPU detected"
fi

# Environment Variables Check
echo "[INIT] Environment Variables:"
echo "  STT_PORT: ${STT_PORT:-8001}"
echo "  TTS_PORT: ${TTS_PORT:-8000}"
echo "  CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-0}"
echo "  WHISPER_DEVICE: ${WHISPER_DEVICE:-cuda}"
echo "  TTS_HOME: ${TTS_HOME:-/app/models}"
echo "  PYTHONPATH: ${PYTHONPATH:-/app}"
echo "  TAILSCALE_AUTH_KEY: ${TAILSCALE_AUTH_KEY:+[SET]}"

# Directory validation
echo "[INIT] Validating directories..."
for dir in "/app/models" "/app/cache" "/var/log/supervisor" "/var/run" "/var/lib/tailscale" "/var/run/tailscale"; do
    if [ -d "$dir" ]; then
        echo "  ✓ $dir exists"
    else
        echo "  ✗ $dir missing, creating..."
        mkdir -p "$dir"
    fi
done

# Python version
echo "[INIT] Python version: $(python --version)"

# Package validation
echo "[INIT] Checking critical packages..."
for pkg in "fastapi" "uvicorn" "torch" "faster-whisper" "coqui-tts"; do
    if python -c "import $pkg" 2>/dev/null; then
        echo "  ✓ $pkg"
    else
        echo "  ✗ $pkg missing!"
    fi
done

# Service files validation
echo "[INIT] Validating service files..."
for file in "/app/stt/main.py" "/app/tts/main.py" "/etc/supervisor/conf.d/supervisord.conf" "/app/tailscale-userspace.sh"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file exists"
    else
        echo "  ✗ $file missing!"
    fi
done

echo "[INIT] Pre-flight checks completed ✓"

# Start Tailscale in userspace mode if auth key is provided
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] Connecting to Headscale network..."
    
    # Set test endpoint for connectivity verification
    export TAILSCALE_TEST_ENDPOINT="${TAILSCALE_TEST_ENDPOINT:-http://june-orchestrator.june-services.svc.cluster.local:8080/health}"
    
    # Run Tailscale userspace networking setup
    if [ -f "/app/tailscale-userspace.sh" ]; then
        chmod +x /app/tailscale-userspace.sh
        /app/tailscale-userspace.sh
    else
        echo "[TAILSCALE] WARNING: tailscale-userspace.sh not found, skipping VPN setup"
    fi
else
    echo "[TAILSCALE] No auth key provided, skipping Tailscale setup"
fi

# Export proxy environment variables for services
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[SERVICES] Setting up proxy environment for Tailscale connectivity..."
    export ALL_PROXY=socks5://localhost:1055/
    export HTTP_PROXY=http://localhost:1055/
    export http_proxy=http://localhost:1055/
    export HTTPS_PROXY=http://localhost:1055/
    export https_proxy=http://localhost:1055/
    
    echo "[SERVICES] Proxy configuration:"
    echo "  ALL_PROXY: $ALL_PROXY"
    echo "  HTTP_PROXY: $HTTP_PROXY"
fi

# Start services based on available supervisor config
if [ -f "/etc/supervisor/conf.d/supervisord.conf" ]; then
    echo "[SERVICES] Starting services via supervisor..."
    exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
else
    echo "[SERVICES] Starting services directly..."
    
    # Start TTS service in background
    echo "[SERVICES] Starting TTS service on port ${TTS_PORT:-8000}..."
    cd /app && python tts/main.py &
    
    # Start STT service in background  
    echo "[SERVICES] Starting STT service on port ${STT_PORT:-8001}..."
    cd /app && python stt/main.py &
    
    # Wait for services to initialize
    sleep 10
    
    # Health checks
    echo "[SERVICES] Performing health checks..."
    curl -f http://localhost:${TTS_PORT:-8000}/healthz && echo "  ✓ TTS service healthy" || echo "  ✗ TTS service unhealthy"
    curl -f http://localhost:${STT_PORT:-8001}/healthz && echo "  ✓ STT service healthy" || echo "  ✗ STT service unhealthy"
    
    echo "[SERVICES] All services started. Container ready."
    
    # Keep container running
    while true; do
        sleep 30
        # Simple health monitoring
        if ! pgrep -f "python.*main.py" > /dev/null; then
            echo "[ERROR] Service processes died, exiting..."
            exit 1
        fi
    done
fi
