#!/bin/bash
set -e

echo "=========================================="
echo "🚀 June TTS - CosyVoice2 Startup"
echo "=========================================="

# Environment info
echo "📋 Environment:"
echo "   MODEL_DIR: ${MODEL_DIR:-/app/pretrained_models}"
echo "   SERVICE_PORT: ${SERVICE_PORT:-8000}"
echo "   CUDA Available: $(python -c 'import torch; print(torch.cuda.is_available())')"
echo ""

# Create and fix permissions on model directory
MODEL_DIR="${MODEL_DIR:-/app/pretrained_models}"
mkdir -p "$MODEL_DIR"

echo "🔧 Checking permissions on $MODEL_DIR"
if [ "$(stat -c %u $MODEL_DIR)" != "1001" ]; then
    echo "   Fixing permissions..."
    sudo chown -R 1001:1001 "$MODEL_DIR" 2>/dev/null || \
        echo "   ⚠️  Warning: Could not fix permissions (continuing anyway)"
fi

# Check if model exists and is complete
MODEL_PATH="$MODEL_DIR/CosyVoice2-0.5B"
CONFIG_FILE="$MODEL_PATH/cosyvoice2.yaml"
BLANKEN_CONFIG="$MODEL_PATH/CosyVoice-BlankEN/config.json"

if [ -f "$CONFIG_FILE" ] && [ -f "$BLANKEN_CONFIG" ]; then
    echo "✅ Model found at $MODEL_PATH"
    FILE_COUNT=$(ls -1 "$MODEL_PATH" | wc -l)
    echo "   Files: $FILE_COUNT"
elif [ -f "$CONFIG_FILE" ]; then
    echo "⚠️  Model found but BlankEN is missing"
    echo "   Expected: $BLANKEN_CONFIG"
    echo ""
    echo "🔄 Downloading missing dependencies..."
    echo ""
    
    if python download_models.py; then
        echo ""
        echo "✅ Dependencies downloaded"
    else
        echo ""
        echo "❌ ERROR: Failed to download dependencies!"
        exit 1
    fi
else
    echo "📦 Model not found or incomplete"
    echo "   Expected: $CONFIG_FILE"
    echo ""
    echo "🔄 Starting model download (this may take 5-10 minutes)..."
    echo ""
    
    # Clear any partial downloads first
    if [ -d "$MODEL_PATH" ]; then
        echo "🧹 Clearing partial download at $MODEL_PATH"
        rm -rf "$MODEL_PATH"
    fi
    
    if [ -d "/tmp/modelscope_cache" ]; then
        echo "🧹 Clearing ModelScope cache"
        rm -rf "/tmp/modelscope_cache"
    fi
    
    # Run download script with detailed output
    if python download_models.py; then
        echo ""
        echo "✅ Model download completed"
    else
        echo ""
        echo "❌ ERROR: Model download failed!"
        echo "   Please check the logs above for details"
        exit 1
    fi
    
    # Verify download succeeded
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "❌ ERROR: Model verification failed!"
        echo "   Expected file not found: $CONFIG_FILE"
        echo ""
        echo "📁 Contents of $MODEL_PATH:"
        ls -la "$MODEL_PATH" 2>/dev/null || echo "   Directory does not exist"
        exit 1
    fi
fi

# List model files for verification
echo ""
echo "📁 Model directory contents:"
ls -lh "$MODEL_PATH" | head -20
FILE_COUNT=$(ls -1 "$MODEL_PATH" | wc -l)
echo "   Total files: $FILE_COUNT"

# Verify critical components
echo ""
echo "🔍 Verifying critical files:"
if [ -f "$CONFIG_FILE" ]; then
    echo "   ✅ cosyvoice2.yaml"
else
    echo "   ❌ cosyvoice2.yaml MISSING!"
    exit 1
fi

if [ -f "$BLANKEN_CONFIG" ]; then
    echo "   ✅ CosyVoice-BlankEN/config.json"
else
    echo "   ❌ CosyVoice-BlankEN model MISSING!"
    echo "      This is required for text processing"
    exit 1
fi

# Enhanced model weights verification
REQUIRED_WEIGHTS=("llm.pt" "flow.pt" "hift.pt")
MISSING_WEIGHTS=()

for weight_file in "${REQUIRED_WEIGHTS[@]}"; do
    if [ ! -f "$MODEL_PATH/$weight_file" ]; then
        MISSING_WEIGHTS+=("$weight_file")
    fi
done

if [ ${#MISSING_WEIGHTS[@]} -eq 0 ]; then
    echo "   ✅ All required model weights found (llm.pt, flow.pt, hift.pt)"
else
    echo "   ❌ Critical model weights MISSING!"
    echo "   Required files: ${REQUIRED_WEIGHTS[*]}"
    echo "   Missing files: ${MISSING_WEIGHTS[*]}"
    echo ""
    echo "   📋 Available .pt files:"
    ls -la "$MODEL_PATH"/*.pt 2>/dev/null || echo "      No .pt files found"
    echo ""
    echo "   💡 This indicates an incomplete model download."
    echo "      Clearing cache and forcing re-download..."
    
    # Force clean re-download
    rm -rf "$MODEL_PATH"
    rm -rf "/tmp/modelscope_cache"
    
    echo "   🔄 Attempting fresh download..."
    if python download_models.py; then
        echo "   ✅ Re-download completed"
        
        # Re-verify after download
        MISSING_WEIGHTS=()
        for weight_file in "${REQUIRED_WEIGHTS[@]}"; do
            if [ ! -f "$MODEL_PATH/$weight_file" ]; then
                MISSING_WEIGHTS+=("$weight_file")
            fi
        done
        
        if [ ${#MISSING_WEIGHTS[@]} -eq 0 ]; then
            echo "   ✅ All model weights now present"
        else
            echo "   ❌ Re-download failed - still missing: ${MISSING_WEIGHTS[*]}"
            echo "   💡 Try manual download: git clone https://www.modelscope.cn/iic/CosyVoice2-0.5B.git $MODEL_PATH"
            exit 1
        fi
    else
        echo "   ❌ Re-download failed!"
        exit 1
    fi
fi

echo ""

echo "=========================================="
echo "🎵 Starting CosyVoice2 TTS Service"
echo "=========================================="
exec python main.py