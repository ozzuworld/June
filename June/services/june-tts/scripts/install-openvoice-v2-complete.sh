#!/bin/bash

# OpenVoice V2 Complete Installation Script
# Following the exact official method + automated checkpoint download
# Uses the official S3 link for V2 checkpoints

set -e

# Install libmagic (for python-magic)
echo "📦 Installing libmagic system dependency..."
apt-get update && apt-get install -y libmagic1 libmagic-dev

echo "🚀 OpenVoice V2 Complete Installation"
echo "====================================="

# Step 1: Install the base package (Official method)
echo "1️⃣ Creating conda environment with Python 3.9..."
conda create -n openvoice python=3.9 -y

echo "✅ Activating openvoice environment..."
eval "$(conda shell.bash hook)"
conda activate openvoice

echo "📦 Cloning OpenVoice repository..."
git clone https://github.com/myshell-ai/OpenVoice.git
cd OpenVoice

echo "🔧 Installing OpenVoice..."
pip install -e .

# Step 2: Automated V2 checkpoint download (using your S3 link)
echo "2️⃣ Downloading OpenVoice V2 checkpoints..."

CHECKPOINTS_URL="https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip"

if [ -d "checkpoints_v2" ] && [ "$(ls -A checkpoints_v2)" ]; then
    echo "✅ V2 checkpoints already exist, skipping download"
else
    echo "📥 Downloading V2 checkpoints from official S3..."
    
    # Create temp directory for download
    mkdir -p /tmp/openvoice_v2_download
    cd /tmp/openvoice_v2_download
    
    # Download with retry logic
    wget --retry-connrefused --waitretry=3 --read-timeout=60 --timeout=60 -t 3 \
         --progress=bar:force:noscroll -O checkpoints_v2.zip \
         "$CHECKPOINTS_URL"
    
    if [ ! -f "checkpoints_v2.zip" ]; then
        echo "❌ Failed to download V2 checkpoints"
        exit 1
    fi
    
    # Verify download size
    FILESIZE=$(stat -c%s checkpoints_v2.zip)
    if [ "$FILESIZE" -lt 1000000 ]; then
        echo "❌ Downloaded file too small, download failed"
        exit 1
    fi
    
    echo "📁 Extracting V2 checkpoints..."
    cd /workspace/OpenVoice  # or wherever your OpenVoice directory is
    unzip -q /tmp/openvoice_v2_download/checkpoints_v2.zip
    
    if [ ! -d "checkpoints_v2" ]; then
        echo "❌ Checkpoint extraction failed"
        exit 1
    fi
    
    # Cleanup temp files
    rm -rf /tmp/openvoice_v2_download
    
    echo "✅ V2 checkpoints downloaded and extracted"
fi

# Verify checkpoint structure
echo "🔍 Verifying checkpoint structure..."
if [ -d "checkpoints_v2/base_speakers" ]; then
    echo "✅ Base speakers found"
fi
if [ -d "checkpoints_v2/converter" ]; then
    echo "✅ Converter found"
fi
if [ -f "checkpoints_v2/config.json" ]; then
    echo "✅ Config found"
fi

CHECKPOINT_FILES=$(find checkpoints_v2 -name "*.pth" | wc -l)
echo "✅ Found $CHECKPOINT_FILES checkpoint files"

# Step 3: Install MeloTTS (Official method)
echo "3️⃣ Installing MeloTTS..."
pip install git+https://github.com/myshell-ai/MeloTTS.git

echo "📚 Downloading UniDic..."
python -m unidic download

echo ""
echo "🎉 OpenVoice V2 Installation Complete!"
echo "======================================"
echo ""
echo "📂 Installation location: $(pwd)"
echo "🐍 Conda environment: openvoice"
echo "📁 V2 checkpoints: $(pwd)/checkpoints_v2"
echo ""
echo "🧪 Test your installation:"
echo "  conda activate openvoice"
echo "  cd $(pwd)"
echo "  python"
echo "  >>> from openvoice.api import ToneColorConverter"
echo "  >>> from melo.api import TTS"
echo ""
echo "✅ Ready to use OpenVoice V2!"