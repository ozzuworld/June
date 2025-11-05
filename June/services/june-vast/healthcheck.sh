#!/usr/bin/env bash
set -e

STT_PORT="${STT_PORT:-8001}"
TTS_PORT="${TTS_PORT:-8000}"

# Check STT service
STT_HEALTH=$(curl -sf "http://localhost:${STT_PORT}/healthz" | grep -o '"status":"healthy"' || echo "")
if [ -z "$STT_HEALTH" ]; then
    echo "❌ STT service unhealthy on port ${STT_PORT}"
    exit 1
fi

# Check TTS service
TTS_HEALTH=$(curl -sf "http://localhost:${TTS_PORT}/health" | grep -o '"status":"healthy"' || echo "")
if [ -z "$TTS_HEALTH" ]; then
    echo "❌ TTS service unhealthy on port ${TTS_PORT}"
    exit 1
fi

echo "✅ Both services healthy"
exit 0