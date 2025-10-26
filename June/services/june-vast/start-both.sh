#!/usr/bin/env bash
set -euo pipefail

# Tailscale: join tailnet if TS_AUTHKEY provided
if command -v tailscale >/dev/null 2>&1; then
  if [ -n "${TS_AUTHKEY:-}" ]; then
    echo "[tailscale] starting and joining tailnet"
    # Run tailscaled in background
    /usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state &
    TSDAEMON_PID=$!
    # Bring interface up
    tailscale up --authkey="$TS_AUTHKEY" --accept-routes --hostname="june-vast-$(hostname)" || true
  else
    echo "[tailscale] TS_AUTHKEY not set; skipping tailscale up"
  fi
else
  echo "[tailscale] not installed"
fi

mkdir -p /app/models /app/cache

# Defaults
export STT_PORT="${STT_PORT:-8001}"
export TTS_PORT="${TTS_PORT:-8000}"
export WHISPER_CACHE_DIR="${WHISPER_CACHE_DIR:-/app/models}"
export TTS_HOME="${TTS_HOME:-/app/models}"
export TTS_CACHE_PATH="${TTS_CACHE_PATH:-/app/cache}"
export COQUI_TOS_AGREED="${COQUI_TOS_AGREED:-1}"

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
