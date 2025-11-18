#!/bin/bash
# Start script for XTTS v2 TTS service

echo "================================================================================"
echo "🚀 Starting XTTS v2 Multilingual TTS Service (Coqui TTS)"
echo "================================================================================"

# Login to Hugging Face if token is provided
if [ -n "$HF_TOKEN" ]; then
    echo "=== Logging in to Hugging Face ==="
    huggingface-cli login --token "$HF_TOKEN"
fi

# Display configuration
echo ""
echo "=== Configuration ==="
echo "   Device: ${DEVICE:-cuda}"
echo "   XTTS Model: ${XTTS_MODEL:-tts_models/multilingual/multi-dataset/xtts_v2}"
echo "   Warmup on startup: ${WARMUP_ON_STARTUP:-0}"
echo "   DeepSpeed enabled: ${USE_DEEPSPEED:-0}"
echo "   HuggingFace cache: ${HF_HOME:-/app/.cache/huggingface}"
echo ""
echo "=== XTTS v2 Features ==="
echo "   Languages: 17 (en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, hu, ko, hi)"
echo "   Voice Cloning: Supported (6+ seconds recommended)"
echo "   Streaming: Enabled (<200ms latency)"
echo ""

# Note about model download
echo ""
echo "=== XTTS v2 Model Info ==="
echo "   Models will be downloaded automatically on first use"
echo "   - XTTS v2 model: ~2GB"
echo "   Location: ${HF_HOME:-/app/.cache/huggingface}"
echo "   First startup may take 5-10 minutes (model download + warmup)"
echo ""

# Create necessary directories
mkdir -p /app/voices
echo "✓ Directories created"

# Start FastAPI service
cd /app
echo "================================================================================"
echo "🎙️  Starting XTTS v2 FastAPI Server"
echo "   Port: 8000"
echo "   Workers: 1 (GPU-based, single model instance)"
echo "   Expected Latency: <200ms (with streaming)"
echo "================================================================================"
echo ""

exec python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
