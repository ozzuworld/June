#!/usr/bin/env python3
"""
CosyVoice2 Model Download - Official Pattern
Based on FunAudioLLM/CosyVoice official documentation
"""

import os
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("model-download")

def download_cosyvoice2_official():
    """
    Download CosyVoice2-0.5B using official method
    Reference: https://github.com/FunAudioLLM/CosyVoice
    """
    
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    model_name = "CosyVoice2-0.5B"
    local_path = os.path.join(model_dir, model_name)
    
    os.makedirs(model_dir, exist_ok=True)
    
    logger.info("=" * 70)
    logger.info("CosyVoice2-0.5B Model Download (Official Method)")
    logger.info("=" * 70)
    logger.info(f"Target: {local_path}")
    logger.info("")
    
    # Check if already exists
    config_file = os.path.join(local_path, "cosyvoice2.yaml")
    if os.path.exists(config_file):
        file_count = len(list(Path(local_path).glob("*")))
        logger.info(f"✅ Model already exists: {local_path}")
        logger.info(f"   Files: {file_count}")
        return local_path
    
    # Import modelscope
    try:
        from modelscope import snapshot_download
    except ImportError:
        logger.error("❌ modelscope package not installed!")
        logger.error("   Install with: pip install modelscope")
        sys.exit(1)
    
    logger.info("📦 Downloading CosyVoice2-0.5B from ModelScope")
    logger.info(f"   Model ID: iic/{model_name}")
    logger.info(f"   Destination: {local_path}")
    logger.info("")
    logger.info("This will download ~3.4GB and may take 5-10 minutes...")
    logger.info("")
    
    try:
        # Official download method from CosyVoice repo
        result = snapshot_download(
            f'iic/{model_name}',
            local_dir=local_path
        )
        
        logger.info("")
        logger.info("✅ Download completed!")
        logger.info(f"   Location: {result}")
        
        # Verify critical files
        verify_model(result)
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("1. Check your internet connection")
        logger.error("2. Make sure modelscope is installed: pip install modelscope")
        logger.error("3. Check ModelScope status: https://modelscope.cn/")
        sys.exit(1)


def verify_model(model_path: str):
    """Verify downloaded model has all required files"""
    logger.info("")
    logger.info("🔍 Verifying model files...")
    
    required_files = [
        "cosyvoice2.yaml",  # Main config - REQUIRED
        "flow.pt",          # Flow model - REQUIRED  
        "hift.pt",          # HiFi-GAN - REQUIRED
        "llm.pt",           # LLM weights - REQUIRED
    ]
    
    missing = []
    for file in required_files:
        file_path = os.path.join(model_path, file)
        if os.path.exists(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"   ✅ {file} ({size_mb:.1f} MB)")
        else:
            logger.error(f"   ❌ {file} MISSING!")
            missing.append(file)
    
    # Check for CosyVoice-BlankEN (tokenizer)
    blanken_path = os.path.join(model_path, "CosyVoice-BlankEN")
    if os.path.exists(blanken_path):
        logger.info(f"   ✅ CosyVoice-BlankEN/ (tokenizer)")
    else:
        logger.warning(f"   ⚠️  CosyVoice-BlankEN/ not found")
        logger.warning("      This directory should contain tokenizer files")
        logger.warning("      The model may not work properly without it")
    
    if missing:
        logger.error("")
        logger.error(f"❌ Model verification FAILED!")
        logger.error(f"   Missing files: {', '.join(missing)}")
        logger.error("")
        logger.error("The download may be incomplete. Try:")
        logger.error("1. Delete the model directory")
        logger.error("2. Run this script again")
        sys.exit(1)
    
    logger.info("")
    logger.info("✅ Model verification passed!")


if __name__ == "__main__":
    logger.info("🚀 Starting CosyVoice2 model download")
    logger.info("")
    
    model_path = download_cosyvoice2_official()
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("🎉 Setup Complete!")
    logger.info("=" * 70)
    logger.info(f"Model ready at: {model_path}")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Start the TTS service with: python main_fixed.py")
    logger.info("2. Or use Docker: docker-compose up")
    logger.info("")