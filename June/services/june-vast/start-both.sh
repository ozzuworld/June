#!/usr/bin/env bash
set -euo pipefail

echo "================================================================"
echo "June vast.ai Combined Services (STT + TTS with CosyVoice2)"
echo "================================================================"

# Environment configuration
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://api.ozzu.world}"
export STT_PORT="${STT_PORT:-8001}"
export TTS_PORT="${TTS_PORT:-8000}"
export WHISPER_CACHE_DIR="${WHISPER_CACHE_DIR:-/app/models}"
export MODEL_DIR="${MODEL_DIR:-/app/pretrained_models}"
export COSYVOICE_MODEL="${COSYVOICE_MODEL:-CosyVoice2-0.5B}"

echo "[config] ORCHESTRATOR_URL: $ORCHESTRATOR_URL"
echo "[config] STT_PORT: $STT_PORT"
echo "[config] TTS_PORT: $TTS_PORT"
echo "[config] WHISPER_CACHE_DIR: $WHISPER_CACHE_DIR"
echo "[config] MODEL_DIR: $MODEL_DIR"

# Create necessary directories
mkdir -p "$WHISPER_CACHE_DIR" "$MODEL_DIR" /app/cache

# Check if CosyVoice2 model exists, download if not
COSYVOICE_MODEL_PATH="$MODEL_DIR/$COSYVOICE_MODEL"
if [ ! -d "$COSYVOICE_MODEL_PATH" ] || [ -z "$(ls -A "$COSYVOICE_MODEL_PATH" 2>/dev/null)" ]; then
    echo "================================================================"
    echo "[download] CosyVoice2 model not found, downloading..."
    echo "================================================================"
    
    /venv-tts/bin/python /app/tts/download_models.py || {
        echo "[error] Failed to download CosyVoice2 model"
        exit 1
    }
else
    echo "[info] CosyVoice2 model already exists at $COSYVOICE_MODEL_PATH"
fi

# Function to handle graceful shutdown
cleanup() {
    echo ""
    echo "================================================================"
    echo "[shutdown] Terminating services..."
    echo "================================================================"
    
    # Send TERM signal to both processes
    kill -TERM "$STT_PID" "$TTS_PID" 2>/dev/null || true
    
    # Wait for graceful shutdown (5 seconds)
    sleep 5
    
    # Force kill if still running
    kill -KILL "$STT_PID" "$TTS_PID" 2>/dev/null || true
    
    # Wait for processes to exit
    wait "$STT_PID" "$TTS_PID" 2>/dev/null || true
    
    echo "[shutdown] Cleanup complete"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Start STT service
echo "================================================================"
echo "[stt] Starting Speech-to-Text service..."
echo "================================================================"
/venv-stt/bin/python /app/stt/main.py &
STT_PID=$!
echo "[stt] Started with PID: $STT_PID on port $STT_PORT"

# Wait a moment before starting TTS
sleep 2

# Start TTS service
echo "================================================================"
echo "[tts] Starting Text-to-Speech service (CosyVoice2)..."
echo "================================================================"
/venv-tts/bin/python /app/tts/main.py &
TTS_PID=$!
echo "[tts] Started with PID: $TTS_PID on port $TTS_PORT"

echo "================================================================"
echo "Both services started successfully!"
echo "================================================================"
echo "STT: http://localhost:$STT_PORT"
echo "TTS: http://localhost:$TTS_PORT"
echo "================================================================"

# Monitor both services
echo "[monitor] Monitoring services (press Ctrl+C to stop)..."

while true; do
    # Check if STT process is still alive
    if ! kill -0 "$STT_PID" 2>/dev/null; then
        echo ""
        echo "[error] STT service (PID: $STT_PID) has died unexpectedly"
        cleanup
        exit 1
    fi
    
    # Check if TTS process is still alive
    if ! kill -0 "$TTS_PID" 2>/dev/null; then
        echo ""
        echo "[error] TTS service (PID: $TTS_PID) has died unexpectedly"
        cleanup
        exit 1
    fi
    
    # Sleep before next check
    sleep 5
done