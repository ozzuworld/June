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

# Baseline env for numerical libs to avoid caching issues
export NUMBA_DISABLE_JIT=${NUMBA_DISABLE_JIT:-1}
export NUMBA_CACHE_DIR=${NUMBA_CACHE_DIR:-/tmp/numba_cache}
export PYTORCH_JIT=${PYTORCH_JIT:-0}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
mkdir -p "$NUMBA_CACHE_DIR" /tmp/torch_cache
chown -R juneuser:juneuser "$NUMBA_CACHE_DIR" /tmp/torch_cache || true

# Display environment
echo "[INIT] Environment Variables:"
echo "  STT_PORT: ${STT_PORT:-8001}"
echo "  TTS_PORT: ${TTS_PORT:-8000}"
echo "  CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-0}"
echo "  WHISPER_DEVICE: ${WHISPER_DEVICE:-cuda}"
echo "  TTS_HOME: ${TTS_HOME:-/app/models}"
echo "  PYTHONPATH: ${PYTHONPATH:-/app}"
echo "  TAILSCALE_AUTH_KEY: ${TAILSCALE_AUTH_KEY:+[SET]}"
echo "  NUMBA_DISABLE_JIT: ${NUMBA_DISABLE_JIT}"
echo "  NUMBA_CACHE_DIR: ${NUMBA_CACHE_DIR}"

# Validate critical directories
echo "[INIT] Validating directories..."
for dir in /app/models /app/cache /var/log/supervisor /var/run /var/lib/tailscale /var/run/tailscale "$NUMBA_CACHE_DIR"; do
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

# Verify Tailscale auth key if we expect to use Tailscale
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    echo "[TAILSCALE] Tailscale auth key provided - will be managed by supervisor"
else
    echo "[TAILSCALE] No auth key provided, Tailscale will be disabled"
fi

echo "[INIT] Starting services with Supervisor (including Tailscale userspace networking)..."

# Start supervisor in foreground - it will manage Tailscale, STT, and TTS
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
