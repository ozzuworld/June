# File: June/services/june-chatterbox-tts/download_models.py

#!/usr/bin/env python3
"""
Download and cache Chatterbox models
"""

import os
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_chatterbox_models():
    """Download Chatterbox models if not already cached"""
    
    try:
        # Import here to trigger download if needed
        from chatterbox.tts import ChatterboxTTS
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        
        logger.info("📥 Downloading Chatterbox English model...")
        model = ChatterboxTTS.from_pretrained(device="cpu")  # Use CPU for download
        logger.info("✅ English model downloaded successfully")
        
        # Download multilingual model if enabled
        if os.getenv("ENABLE_MULTILINGUAL", "true").lower() == "true":
            logger.info("📥 Downloading Chatterbox Multilingual model...")
            multilingual_model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
            logger.info("✅ Multilingual model downloaded successfully")
        
        logger.info("🎉 All models downloaded successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to download models: {e}")
        raise

if __name__ == "__main__":
    download_chatterbox_models()
