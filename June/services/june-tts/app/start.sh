#!/bin/bash
# Start script for Chatterbox TTS service

echo "=" * 80
echo "🚀 Starting Chatterbox TTS Service"
echo "=" * 80

# Login to Hugging Face if token is provided
if [ -n "$HF_TOKEN" ]; then
    echo "=== Logging in to Hugging Face ==="
    huggingface-cli login --token "$HF_TOKEN"
fi

# Display configuration
echo "=== Configuration ==="
echo "   Device: ${DEVICE:-cuda}"
echo "   Multilingual: ${USE_MULTILINGUAL:-1}"
echo "   Warmup on startup: ${WARMUP_ON_STARTUP:-1}"
echo "   Max workers: ${MAX_WORKERS:-2}"
echo "   HuggingFace cache: ${HF_HOME:-/app/.cache/huggingface}"

# Note about model download
echo ""
echo "=== Chatterbox Model Info ==="
echo "   Models will be downloaded automatically on first use"
if [ "${USE_MULTILINGUAL:-1}" = "1" ]; then
    echo "   Model: ResembleAI/chatterbox-mtl (Multilingual - 23 languages)"
else
    echo "   Model: ResembleAI/chatterbox (English only)"
fi
echo "   Location: ~/.cache/huggingface/hub/"
echo "   First startup may take 5-10 minutes (model download + warmup compilation)"
echo ""

# Create necessary directories
mkdir -p /app/voices
mkdir -p /app/references
echo "✓ Directories created"

# Start FastAPI service
cd /app
echo "=" * 80
echo "🎙️  Starting Chatterbox TTS FastAPI Server"
echo "   Port: 8000"
echo "   Workers: 1 (GPU-based, single model instance)"
echo "=" * 80

exec python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
