#!/bin/bash
set -e

echo "=========================================="
echo "🚀 June TTS - CosyVoice2 Startup"
echo "=========================================="

# Environment info
echo "📋 Environment:"
echo "   MODEL_DIR: ${MODEL_DIR:-/app/pretrained_models}"
echo "   SERVICE_PORT: ${SERVICE_PORT:-8000}"
echo "   CUDA Available: $(python -c 'import torch; print(torch.cuda.is_available())' 2>/dev/null || echo 'unknown')"
echo ""

# Create and fix permissions on model directory
MODEL_DIR="${MODEL_DIR:-/app/pretrained_models}"
mkdir -p "$MODEL_DIR"

echo "🔧 Checking permissions on $MODEL_DIR"
if [ "$(stat -c %u $MODEL_DIR 2>/dev/null)" != "1001" ]; then
    echo "   Fixing permissions..."
    sudo chown -R 1001:1001 "$MODEL_DIR" 2>/dev/null || \
        echo "   ⚠️  Warning: Could not fix permissions (continuing anyway)"
fi

# Check if model exists and is complete
MODEL_PATH="$MODEL_DIR/CosyVoice2-0.5B"
CONFIG_FILE="$MODEL_PATH/cosyvoice2.yaml"

if [ -f "$CONFIG_FILE" ]; then
    echo "✅ Model found at $MODEL_PATH"
    FILE_COUNT=$(ls -1 "$MODEL_PATH" 2>/dev/null | wc -l)
    echo "   Files: $FILE_COUNT"
    
    # Check for BlankEN (optional)
    BLANKEN_CONFIG="$MODEL_PATH/CosyVoice-BlankEN/config.json"
    if [ -f "$BLANKEN_CONFIG" ]; then
        echo "   ✅ BlankEN available"
    else
        echo "   ⚠️  BlankEN not found (optional)"
    fi
else
    echo "📦 Model not found or incomplete"
    echo "   Expected: $CONFIG_FILE"
    echo ""
    echo "🔄 Starting model download (this may take 5-10 minutes)..."
    echo ""
    
    # Run download script
    if python download_models.py; then
        echo ""
        echo "✅ Model download completed"
    else
        echo ""
        echo "❌ ERROR: Model download failed!"
        echo "   Please check the logs above for details"
        exit 1
    fi
    
    # Verify download succeeded (only check critical files)
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "❌ ERROR: Model verification failed!"
        echo "   Expected file not found: $CONFIG_FILE"
        exit 1
    fi
fi

# List model files for verification
echo ""
echo "📁 Model directory contents:"
ls -lh "$MODEL_PATH" 2>/dev/null | head -20 || echo "   Cannot list directory"
FILE_COUNT=$(ls -1 "$MODEL_PATH" 2>/dev/null | wc -l || echo "0")
echo "   Total files: $FILE_COUNT"

# Verify ONLY critical files (not optional BlankEN)
echo ""
echo "🔍 Verifying critical files:"

if [ -f "$CONFIG_FILE" ]; then
    echo "   ✅ cosyvoice2.yaml"
else
    echo "   ❌ cosyvoice2.yaml MISSING!"
    exit 1
fi

if [ -f "$MODEL_PATH/flow.pt" ]; then
    echo "   ✅ flow.pt"
else
    echo "   ❌ flow.pt MISSING!"
    exit 1
fi

if [ -f "$MODEL_PATH/hift.pt" ]; then
    echo "   ✅ hift.pt"
else
    echo "   ❌ hift.pt MISSING!"
    exit 1
fi

# BlankEN is OPTIONAL - just warn if missing
BLANKEN_CONFIG="$MODEL_PATH/CosyVoice-BlankEN/config.json"
if [ -f "$BLANKEN_CONFIG" ]; then
    echo "   ✅ CosyVoice-BlankEN (optional)"
else
    echo "   ⚠️  CosyVoice-BlankEN not found (optional - may not be needed)"
fi

echo ""
echo "=========================================="
echo "🎵 Starting CosyVoice2 TTS Service"
echo "=========================================="

# Use main.py (not main_fixed.py)
exec python main.py