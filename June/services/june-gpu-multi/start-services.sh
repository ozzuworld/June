#!/bin/bash
# Start script for multi-service GPU container with Tailscale
# This file has Unix line endings (LF) - do not edit on Windows without dos2unix

set -e

echo "[INIT] Starting June GPU Multi-Service Container with Tailscale"
echo "[INIT] Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"

# Check for GPU
echo "[INIT] GPU Detection:"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi -L 2>/dev/null || echo "[WARN] nvidia-smi found but no GPU detected (OK for local testing)"
else
    echo "[WARN] nvidia-smi not found (OK for local testing without GPU)"
fi

# Display environment
echo "[INIT] Environment Variables:"
echo "  STT_PORT: ${STT_PORT:-8001}"
echo "  TTS_PORT: ${TTS_PORT:-8000}"
echo "  CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-0}"
echo "  WHISPER_DEVICE: ${WHISPER_DEVICE:-cuda}"
echo "  TTS_HOME: ${TTS_HOME:-/app/models}"
echo "  PYTHONPATH: ${PYTHONPATH:-/app}"
echo "  TAILSCALE_AUTH_KEY: ${TAILSCALE_AUTH_KEY:+[SET]}"

# Validate critical directories
echo "[INIT] Validating directories..."
for dir in /app/models /app/cache /var/log/supervisor /var/run /var/lib/tailscale /var/run/tailscale; do
    if [ ! -d "$dir" ]; then
        echo "[ERROR] Required directory missing: $dir"
        exit 1
    fi
    echo "  ✓ $dir exists"
done

# Check Python and dependencies
echo "[INIT] Python version: $(python --version)"
echo "[INIT] Checking critical packages..."
python -c "import fastapi; print('  ✓ fastapi')" || { echo "[ERROR] fastapi not installed"; exit 1; }
python -c "import uvicorn; print('  ✓ uvicorn')" || { echo "[ERROR] uvicorn not installed"; exit 1; }
python -c "import torch; print('  ✓ torch')" || { echo "[ERROR] torch not installed"; exit 1; }
python -c "import faster_whisper; print('  ✓ faster-whisper')" || { echo "[ERROR] faster-whisper not installed"; exit 1; }
python -c "from TTS.api import TTS; print('  ✓ coqui-tts')" || { echo "[ERROR] coqui-tts not installed"; exit 1; }

# Verify service files exist
echo "[INIT] Validating service files..."
for file in /app/stt/main.py /app/tts/main.py /etc/supervisor/conf.d/supervisord.conf /app/tailscale-connect.sh; do
    if [ ! -f "$file" ]; then
        echo "[ERROR] Required file missing: $file"
        exit 1
    fi
    echo "  ✓ $file exists"
done

# Create necessary runtime directories
mkdir -p /var/log/supervisor /var/run
touch /var/log/supervisor/supervisord.log

echo "[INIT] Pre-flight checks completed ✓"

# Start Tailscale connection if auth key is provided
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] Connecting to headscale network..."
    /app/tailscale-connect.sh &
    TAILSCALE_PID=$!
    
    # Wait a moment for Tailscale to initialize
    sleep 10
    
    # Verify Tailscale connection (non-blocking)
    if tailscale status >/dev/null 2>&1; then
        echo "[TAILSCALE] ✅ Connected to headscale network!"
    else
        echo "[TAILSCALE] ⚠️  Tailscale connecting in background..."
    fi
else
    echo "[TAILSCALE] No auth key provided, skipping Tailscale connection"
fi

echo "[INIT] Starting AI services with Supervisor..."

# Start supervisor in foreground
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf