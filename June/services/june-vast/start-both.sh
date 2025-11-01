#!/usr/bin/env bash
set -euo pipefail

echo "[june-vast] Starting june-vast services without Tailscale"

# Use direct communication with orchestrator
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://api.ozzu.world}"

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
  
  # Give processes time to cleanup gracefully
  sleep 2
  
  # Force kill if necessary
  kill -KILL "$STT_PID" "$TTS_PID" 2>/dev/null || true
  
  wait "$STT_PID" "$TTS_PID" 2>/dev/null || true
  
  # Additional delay to ensure port release
  sleep 1
}
trap term SIGINT SIGTERM

# Wait indefinitely while both services are running
# Only exit if both services fail
echo "[monitor] Monitoring both services..."
while true; do
    # Check if both processes are still alive
    if ! kill -0 "$STT_PID" 2>/dev/null; then
        echo "[error] STT process (PID: $STT_PID) has died"
        break
    fi
    
    if ! kill -0 "$TTS_PID" 2>/dev/null; then
        echo "[error] TTS process (PID: $TTS_PID) has died"
        break
    fi
    
    # Both services are running, sleep and check again
    sleep 5
done

echo "[monitor] One or both services have failed, initiating shutdown"
term
exit 1