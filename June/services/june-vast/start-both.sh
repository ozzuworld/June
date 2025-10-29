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
  wait "$STT_PID" "$TTS_PID" 2>/dev/null || true
}
trap term SIGINT SIGTERM

# Wait on either to exit, then exit with its status
wait -n "$STT_PID" "$TTS_PID"
EXIT_CODE=$?
term
exit "$EXIT_CODE"