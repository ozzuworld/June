#!/bin/bash
# Start script for Fish Speech TTS service

# Login to Hugging Face if token is provided
if [ -n "$HF_TOKEN" ]; then
    echo "=== Logging in to Hugging Face ==="
    huggingface-cli login --token "$HF_TOKEN"
fi

# Check if models exist, download if missing
if [ ! -f "/app/checkpoints/openaudio-s1-mini/config.json" ]; then
    echo "=== Models not found, downloading openaudio-s1-mini ==="
    mkdir -p /app/checkpoints
    huggingface-cli download fishaudio/openaudio-s1-mini \
        --local-dir /app/checkpoints/openaudio-s1-mini \
        --local-dir-use-symlinks False

    echo "=== Verifying downloaded files ==="
    ls -lah /app/checkpoints/openaudio-s1-mini/

    if [ ! -f "/app/checkpoints/openaudio-s1-mini/config.json" ]; then
        echo "ERROR: Model download failed!"
        exit 1
    fi
    echo "✓ Models downloaded successfully"
else
    echo "=== Models already exist, skipping download ==="
    ls -lah /app/checkpoints/openaudio-s1-mini/
fi

# Start Fish Speech API server in the background
cd /opt/fish-speech

# Configure compile flag (default: enabled for 10x speedup)
COMPILE_FLAG=""
if [ "${COMPILE:-1}" = "1" ]; then
    COMPILE_FLAG="--compile"
    echo "=== Torch compile ENABLED (10x speedup) ==="
else
    echo "=== Torch compile DISABLED ==="
fi

python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq \
    $COMPILE_FLAG &

# Wait for Fish Speech API to start
echo "Waiting for Fish Speech API to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:9880/docs > /dev/null 2>&1; then
        echo "✓ Fish Speech API is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "⚠ Fish Speech API not ready after 30s, starting wrapper anyway..."
    fi
    sleep 1
done

# Start our FastAPI wrapper
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
