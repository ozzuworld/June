#!/bin/bash

# Start script for multi-service GPU container
set -e

echo "[INIT] Starting June GPU Multi-Service Container"
echo "[INIT] GPU Info:"
nvidia-smi -L 2>/dev/null || echo "[WARN] No GPU detected"

echo "[INIT] Environment Variables:"
echo "  STT_PORT: ${STT_PORT:-8001}"
echo "  TTS_PORT: ${TTS_PORT:-8000}"
echo "  CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-0}"
echo "  WHISPER_DEVICE: ${WHISPER_DEVICE:-cuda}"
echo "  TTS_HOME: ${TTS_HOME:-/app/models}"

# Create necessary directories
mkdir -p /var/log/supervisor /var/run
touch /var/log/supervisor/supervisord.log

# Ensure proper permissions
chown -R juneuser:juneuser /var/log/supervisor /var/run 2>/dev/null || true

echo "[INIT] Starting services with Supervisor..."

# Start supervisor in foreground
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf