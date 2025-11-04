#!/usr/bin/env python3
"""
CosyVoice2 Model Download Script
Downloads CosyVoice2-0.5B model from ModelScope
"""

import os
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cosyvoice2-download")


def download_cosyvoice2_model():
    """Download CosyVoice2-0.5B model from ModelScope"""
    
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    model_name = "CosyVoice2-0.5B"
    local_path = os.path.join(model_dir, model_name)
    
    # Create directory
    os.makedirs(model_dir, exist_ok=True)
    
    # Check if model already exists
    if os.path.exists(local_path) and os.path.isdir(local_path):
        files = os.listdir(local_path)
        if len(files) > 5:  # Basic check for model files
            logger.info(f"✅ Model already exists at {local_path}")
            logger.info(f"   Found {len(files)} files")
            return local_path
    
    try:
        from modelscope import snapshot_download
        
        logger.info(f"📦 Downloading {model_name} from ModelScope...")
        logger.info(f"   Target directory: {local_path}")
        logger.info("   This may take 5-15 minutes depending on connection speed")
        
        # Download model
        snapshot_download(
            model_id=f'iic/{model_name}',
            local_dir=local_path,
            cache_dir='/tmp/modelscope_cache'
        )
        
        logger.info(f"✅ Model downloaded successfully to {local_path}")
        
        # List downloaded files
        files = os.listdir(local_path)
        logger.info(f"   Downloaded {len(files)} files")
        
        # Check for essential files
        essential_files = ['config.json', 'configuration.json']
        for file in essential_files:
            if os.path.exists(os.path.join(local_path, file)):
                logger.info(f"   ✓ {file}")
            else:
                logger.warning(f"   ⚠ {file} not found")
        
        return local_path
        
    except ImportError as e:
        logger.error(f"❌ ModelScope not available: {e}")
        logger.error("   Install with: pip install modelscope")
        raise
    except Exception as e:
        logger.error(f"❌ Model download failed: {e}")
        raise


def download_ttsfrd_resource():
    """Optionally download CosyVoice-ttsfrd for better text normalization"""
    
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    ttsfrd_path = os.path.join(model_dir, "CosyVoice-ttsfrd")
    
    if os.path.exists(ttsfrd_path):
        logger.info(f"✅ ttsfrd resource already exists at {ttsfrd_path}")
        return ttsfrd_path
    
    try:
        from modelscope import snapshot_download
        
        logger.info("📦 Downloading CosyVoice-ttsfrd resource (optional)...")
        
        snapshot_download(
            model_id='iic/CosyVoice-ttsfrd',
            local_dir=ttsfrd_path,
            cache_dir='/tmp/modelscope_cache'
        )
        
        logger.info(f"✅ ttsfrd resource downloaded to {ttsfrd_path}")
        logger.info("   Note: This resource is optional for text normalization")
        
        return ttsfrd_path
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to download ttsfrd resource (non-critical): {e}")
        return None


if __name__ == "__main__":
    logger.info("🚀 Starting CosyVoice2 model download")
    
    # Download main model
    model_path = download_cosyvoice2_model()
    
    # Optionally download ttsfrd resource
    ttsfrd_path = download_ttsfrd_resource()
    
    logger.info("🎉 Model download complete!")
    logger.info(f"   Model: {model_path}")
    if ttsfrd_path:
        logger.info(f"   ttsfrd: {ttsfrd_path}")
    logger.info("   Ready for TTS synthesis")