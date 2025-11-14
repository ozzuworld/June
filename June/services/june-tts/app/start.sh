#!/bin/bash
# Start script for Fish Speech TTS service

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
python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq \
    --compile &

# Wait for Fish Speech API to start
echo "Waiting for Fish Speech API to start..."
sleep 10

# Start our FastAPI wrapper
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
