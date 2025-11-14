#!/bin/bash
# Start script for Fish Speech TTS service

# Debug: Check if checkpoint directory exists
echo "=== DEBUG: Checking checkpoint directory ==="
ls -la /app/checkpoints/ || echo "ERROR: /app/checkpoints/ does not exist!"
echo ""
echo "=== DEBUG: Checking fish-speech-1.5 directory ==="
ls -la /app/checkpoints/fish-speech-1.5/ || echo "ERROR: /app/checkpoints/fish-speech-1.5/ does not exist!"
echo ""
echo "=== DEBUG: Checking required files ==="
test -f /app/checkpoints/fish-speech-1.5/config.json && echo "✓ config.json exists" || echo "✗ config.json MISSING"
test -f /app/checkpoints/fish-speech-1.5/model.pth && echo "✓ model.pth exists" || echo "✗ model.pth MISSING"
echo ""

# Start Fish Speech API server in the background
cd /opt/fish-speech
python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/fish-speech-1.5 \
    --decoder-checkpoint-path /app/checkpoints/fish-speech-1.5/firefly-gan-vq-fsq-8x1024-21hz-generator.pth \
    --decoder-config-name firefly_gan_vq \
    --compile &

# Wait for Fish Speech API to start
echo "Waiting for Fish Speech API to start..."
sleep 10

# Start our FastAPI wrapper
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
