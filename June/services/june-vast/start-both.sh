#!/usr/bin/env bash
set -euo pipefail

# Tailscale: join tailnet if TS_AUTHKEY provided
if command -v tailscale >/dev/null 2>&1; then
  if [ -n "${TS_AUTHKEY:-}" ]; then
    echo "[tailscale] starting and joining tailnet in userspace mode (vast.ai compatible)"
    
    # Create required directories
    mkdir -p /var/lib/tailscale /var/run/tailscale
    
    # Run tailscaled in userspace networking mode (no kernel TUN required)
    /usr/sbin/tailscaled \
      --state=/var/lib/tailscale/tailscaled.state \
      --socket=/var/run/tailscale/tailscaled.sock \
      --tun=userspace-networking &
    
    TSDAEMON_PID=$!
    
    # Wait longer for socket to be ready in userspace mode
    sleep 10
    
    echo "[tailscale] connecting to headscale..."
    # Connect using socket and specify login server
    tailscale --socket=/var/run/tailscale/tailscaled.sock up \
      --login-server="https://headscale.ozzu.world" \
      --authkey="$TS_AUTHKEY" \
      --accept-routes \
      --hostname="june-vast-$(hostname)" || {
      echo "[tailscale] connection failed, continuing without VPN"
    }
    
    # Quick connectivity test
    if tailscale --socket=/var/run/tailscale/tailscaled.sock status >/dev/null 2>&1; then
      echo "[tailscale] connected successfully"
      # Use private network for service communication
      export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://june-orchestrator.tail.ozzu.world}"
    else
      echo "[tailscale] not connected, using public endpoints"
      export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://api.ozzu.world}"
    fi
  else
    echo "[tailscale] TS_AUTHKEY not set; using public endpoints"
    export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://api.ozzu.world}"
  fi
else
  echo "[tailscale] not installed, using public endpoints"
  export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://api.ozzu.world}"
fi

mkdir -p /app/models /app/cache

# Defaults
export STT_PORT="${STT_PORT:-8001}"
export TTS_PORT="${TTS_PORT:-8000}"
export WHISPER_CACHE_DIR="${WHISPER_CACHE_DIR:-/app/models}"
export TTS_HOME="${TTS_HOME:-/app/models}"
export TTS_CACHE_PATH="${TTS_CACHE_PATH:-/app/cache}"
export COQUI_TOS_AGREED="${COQUI_TOS_AGREED:-1}"

echo "[config] Using ORCHESTRATOR_URL: $ORCHESTRATOR_URL"

# Start STT (whisper)
/venv-stt/bin/python /app/stt/main.py &
STT_PID=$!

echo "[stt] started pid=$STT_PID on port ${STT_PORT}"

# Start TTS (coqui/F5)
/venv-tts/bin/python /app/tts/main.py &
TTS_PID=$!

echo "[tts] started pid=$TTS_PID on port ${TTS_PORT}"

term() {
  echo "[entrypoint] terminating services"
  kill -TERM "$STT_PID" "$TTS_PID" 2>/dev/null || true
  wait "$STT_PID" "$TTS_PID" 2>/dev/null || true
  if [ -n "${TSDAEMON_PID:-}" ]; then
    kill -TERM "$TSDAEMON_PID" 2>/dev/null || true
    wait "$TSDAEMON_PID" 2>/dev/null || true
  fi
}
trap term SIGINT SIGTERM

# Wait on either to exit, then exit with its status
wait -n "$STT_PID" "$TTS_PID"
EXIT_CODE=$?
term
exit "$EXIT_CODE"