#!/bin/bash
# Start script for Orpheus TTS service

echo "================================================================================"
echo "🚀 Starting Orpheus Multilingual TTS Service"
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
echo "   Orpheus Model: ${ORPHEUS_MODEL:-canopylabs/orpheus-3b-0.1-ft}"
echo "   Orpheus Variant: ${ORPHEUS_VARIANT:-english}"
echo "   Warmup on startup: ${WARMUP_ON_STARTUP:-1}"
echo "   Max workers: ${MAX_WORKERS:-2}"
echo "   HuggingFace cache: ${HF_HOME:-/app/.cache/huggingface}"
echo ""
echo "=== vLLM Optimization Settings ==="
echo "   GPU Memory Utilization: ${VLLM_GPU_MEMORY_UTILIZATION:-0.7}"
echo "   Max Model Length: ${VLLM_MAX_MODEL_LEN:-2048}"
echo "   Quantization: ${VLLM_QUANTIZATION:-fp8}"
echo ""
echo "=== Streaming Settings ==="
echo "   Chunk Size: ${ORPHEUS_CHUNK_SIZE:-210} tokens"
echo "   Fade Duration: ${ORPHEUS_FADE_MS:-5}ms"

# Note about model download
echo ""
echo "=== Orpheus Model Info ==="
echo "   Models will be downloaded automatically on first use"
echo "   - Orpheus model: ~3-4GB (includes LLM and audio decoder)"
echo "   Location: ${HF_HOME:-/app/.cache/huggingface}"
echo "   First startup may take 10-15 minutes (model download + warmup)"
echo ""

# Create necessary directories
mkdir -p /app/voices
mkdir -p /app/references
echo "✓ Directories created"

# Start FastAPI service
cd /app
echo "================================================================================"
echo "🎙️  Starting Orpheus TTS FastAPI Server"
echo "   Port: 8000"
echo "   Workers: 1 (GPU-based, single model instance)"
echo "   Expected Latency: 100-200ms (streaming)"
echo "================================================================================"
echo ""

exec python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
