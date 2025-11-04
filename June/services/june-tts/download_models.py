#!/usr/bin/env python3
"""
CosyVoice 2 Model Download Script for June TTS
Downloads the optimal CosyVoice2-0.5B model for streaming synthesis
"""

import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cosyvoice-models")

def download_cosyvoice_models():
    """Download CosyVoice 2 models for streaming TTS"""
    models_dir = "/app/models/cosyvoice"
    os.makedirs(models_dir, exist_ok=True)
    
    try:
        from modelscope import snapshot_download
        
        # Download CosyVoice2-0.5B (optimal balance of speed/quality)
        model_path = os.path.join(models_dir, "CosyVoice2-0.5B")
        
        if os.path.exists(model_path) and len(os.listdir(model_path)) > 0:
            logger.info(f"✅ CosyVoice2-0.5B already exists at {model_path}")
            return
        
        logger.info("📦 Downloading CosyVoice2-0.5B model (optimized for streaming)...")
        logger.info("⏳ This may take 5-10 minutes depending on connection speed")
        
        snapshot_download(
            model_id='iic/CosyVoice2-0.5B',
            local_dir=model_path,
            cache_dir='/tmp/modelscope_cache'
        )
        
        logger.info(f"✅ CosyVoice2-0.5B downloaded successfully to {model_path}")
        
        # Verify essential files
        required_files = ['pytorch_model.bin', 'config.json', 'configuration.json']
        missing_files = []
        
        for file in required_files:
            if not os.path.exists(os.path.join(model_path, file)):
                missing_files.append(file)
        
        if missing_files:
            logger.warning(f"⚠️ Some model files may be missing: {missing_files}")
        else:
            logger.info("✅ All essential model files verified")
            
    except ImportError as e:
        logger.error(f"❌ modelscope not available: {e}")
        logger.error("💡 Install with: pip install modelscope")
        raise
    except Exception as e:
        logger.error(f"❌ Model download failed: {e}")
        raise

if __name__ == "__main__":
    logger.info("🚀 Starting CosyVoice 2 model download for June TTS")
    download_cosyvoice_models()
    logger.info("🎉 Model download complete! Ready for ultra-low latency TTS")