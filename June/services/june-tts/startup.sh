#!/bin/bash
set -e

echo "🚀 Starting June TTS with auto-download"

# Create model directory if it doesn't exist
mkdir -p /app/pretrained_models

# Fix permissions (handle case where volume mounts as root)
if [ "$(stat -c %u /app/pretrained_models)" != "1001" ]; then
    echo "🔧 Fixing permissions on /app/pretrained_models"
    # Try to fix permissions, but don't fail if we can't (non-root container)
    chown -R 1001:1001 /app/pretrained_models 2>/dev/null || \
    sudo chown -R 1001:1001 /app/pretrained_models 2>/dev/null || \
    echo "⚠️  Warning: Could not fix permissions (running as non-root)"
fi

# Check if model exists and has critical files
if [ ! -f "/app/pretrained_models/CosyVoice2-0.5B/cosyvoice2.yaml" ]; then
    echo "📦 Model not found or incomplete, downloading CosyVoice2-0.5B..."
    
    # Run the download script
    python download_models.py
    
    # Verify download completed
    if [ -f "/app/pretrained_models/CosyVoice2-0.5B/cosyvoice2.yaml" ]; then
        echo "✅ Model download completed successfully"
    else
        echo "❌ Model download failed - cosyvoice2.yaml not found"
        exit 1
    fi
else
    echo "✅ Model already exists and appears complete"
fi

# List model files for debugging
echo "📁 Model files:"
ls -la /app/pretrained_models/CosyVoice2-0.5B/ 2>/dev/null || echo "   No model files found"

echo "🎵 Starting TTS service..."
exec python main.py