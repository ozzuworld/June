#!/usr/bin/env bash
set -e

STT_PORT="${STT_PORT:-8001}"
TTS_PORT="${TTS_PORT:-8000}"

echo "================================================================"
echo "June Services Health Check"
echo "================================================================"

# Check STT service
echo -n "STT Service (port $STT_PORT): "
if curl -sf "http://localhost:${STT_PORT}/healthz" > /dev/null 2>&1; then
    echo "✅ HEALTHY"
    STT_STATUS=0
else
    echo "❌ UNHEALTHY"
    STT_STATUS=1
fi

# Check TTS service
echo -n "TTS Service (port $TTS_PORT): "
if curl -sf "http://localhost:${TTS_PORT}/health" > /dev/null 2>&1; then
    echo "✅ HEALTHY"
    TTS_STATUS=0
else
    echo "❌ UNHEALTHY"
    TTS_STATUS=1
fi

echo "================================================================"

# Exit with error if any service is unhealthy
if [ $STT_STATUS -ne 0 ] || [ $TTS_STATUS -ne 0 ]; then
    echo "❌ One or more services are unhealthy"
    exit 1
fi

echo "✅ All services healthy"
exit 0