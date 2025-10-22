#!/bin/bash

# Enhanced June GPU Multi-Service Container Entrypoint
# Streams STT/TTS logs to stdout so errors appear in container logs/console

set -e

DEBUG_MODE=${DEBUG_MODE:-false}

log() { echo "[INIT] $*"; }
warn() { echo "[WARN] $*"; }

log "Starting June GPU Multi-Service Container"
log "Timestamp: $(date -u)"

# Minimal checks
python3 -V || true
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
fi

# Ensure directories
mkdir -p /var/log/supervisor /var/run /app/models /app/cache /var/lib/tailscale /var/run/tailscale || true

if [ "$DEBUG_MODE" = "true" ] && [ -f "/app/debug-services.sh" ]; then
  echo "[DEBUG] Running diagnostics...";
  bash /app/debug-services.sh || true
fi

# Write supervisor config that logs to stdout
cat > /etc/supervisor/conf.d/supervisord.conf << 'EOF'
[supervisord]
nodaemon=true
user=root
logfile=/dev/stdout
logfile_maxbytes=0
loglevel=info
pidfile=/var/run/supervisord.pid

[program:june-stt]
command=python3 /app/stt/main.py
directory=/app
user=root
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
environment=PYTHONPATH=/app:/app/stt:/app/tts,STT_PORT=%(ENV_STT_PORT)s,CUDA_VISIBLE_DEVICES=%(ENV_CUDA_VISIBLE_DEVICES)s

[program:june-tts]
command=python3 /app/tts/main.py
directory=/app
user=root
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
environment=PYTHONPATH=/app:/app/stt:/app/tts,TTS_PORT=%(ENV_TTS_PORT)s,CUDA_VISIBLE_DEVICES=%(ENV_CUDA_VISIBLE_DEVICES)s
EOF

exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
