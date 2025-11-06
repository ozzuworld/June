#!/usr/bin/env python3
"""
CosyVoice2 Model Download Script - SIMPLIFIED & FIXED
Downloads CosyVoice2-0.5B model from ModelScope
Treats BlankEN as optional (not critical)
"""

import os
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("model-download")

MODEL_NAME = "CosyVoice2-0.5B"
MODEL_ID = f"iic/{MODEL_NAME}"
CACHE_DIR = "/tmp/modelscope_cache"


def check_critical_files(model_path: str) -> tuple[bool, list]:
    """Check if all critical model files exist"""
    critical_files = [
        "cosyvoice2.yaml",
        "flow.pt",
        "hift.pt"
    ]
    
    missing = []
    for file in critical_files:
        if not os.path.exists(os.path.join(model_path, file)):
            missing.append(file)
    
    return len(missing) == 0, missing


def download_cosyvoice2_model():
    """Download CosyVoice2-0.5B model - SIMPLIFIED"""
    
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    local_path = os.path.join(model_dir, MODEL_NAME)
    
    os.makedirs(model_dir, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("CosyVoice2 Model Download")
    logger.info("=" * 60)
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Target: {local_path}")
    logger.info("")
    
    # Check if model already exists and is complete
    if os.path.isdir(local_path):
        is_complete, missing = check_critical_files(local_path)
        if is_complete:
            file_count = len(os.listdir(local_path))
            logger.info(f"✅ Model already exists and is complete")
            logger.info(f"   Location: {local_path}")
            logger.info(f"   Files: {file_count}")
            return local_path
        else:
            logger.warning(f"⚠️  Model exists but is incomplete")
            logger.warning(f"   Missing files: {', '.join(missing)}")
            logger.info("   Will re-download...")
            shutil.rmtree(local_path)
    
    # Download via ModelScope
    try:
        from modelscope import snapshot_download
    except ImportError:
        logger.error("❌ modelscope package not installed!")
        logger.error("   Install with: pip install modelscope")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("Downloading via ModelScope SDK")
    logger.info("=" * 60)
    logger.info(f"Model ID: {MODEL_ID}")
    logger.info(f"Target: {local_path}")
    logger.info("This may take 5-10 minutes depending on your connection...")
    logger.info("")
    
    try:
        # Try new API (with local_dir)
        result = snapshot_download(
            model_id=MODEL_ID,
            local_dir=local_path,
            cache_dir=CACHE_DIR,
        )
    except TypeError:
        # Fallback to legacy API (without local_dir)
        logger.info("Using legacy ModelScope API...")
        result = snapshot_download(
            model_id=MODEL_ID,
            cache_dir=CACHE_DIR,
        )
        # Move to target location
        if os.path.exists(result) and result != local_path:
            if os.path.exists(local_path):
                shutil.rmtree(local_path)
            shutil.move(result, local_path)
            result = local_path
    
    # Verify download
    is_complete, missing = check_critical_files(result)
    if not is_complete:
        logger.error(f"❌ Download incomplete. Missing files: {', '.join(missing)}")
        sys.exit(1)
    
    file_count = len(os.listdir(result))
    logger.info("=" * 60)
    logger.info("✅ Download complete and verified")
    logger.info(f"   Location: {result}")
    logger.info(f"   Files: {file_count}")
    logger.info("=" * 60)
    
    return result


def try_download_optional_blanken(model_path: str):
    """Try to download BlankEN - OPTIONAL, doesn't fail if not available"""
    blank_en_path = os.path.join(model_path, "CosyVoice-BlankEN")
    
    # Check if already exists
    if os.path.exists(os.path.join(blank_en_path, "config.json")):
        logger.info("✅ CosyVoice-BlankEN already exists")
        return True
    
    try:
        from modelscope import snapshot_download
        logger.info("")
        logger.info("📦 Attempting to download CosyVoice-BlankEN (optional)...")
        logger.info("   This model may not be available, which is OK")
        
        try:
            snapshot_download(
                model_id='iic/CosyVoice-BlankEN',
                local_dir=blank_en_path,
                cache_dir=CACHE_DIR,
            )
        except TypeError:
            path = snapshot_download(
                model_id='iic/CosyVoice-BlankEN',
                cache_dir=CACHE_DIR,
            )
            if os.path.exists(path) and path != blank_en_path:
                shutil.move(path, blank_en_path)
        
        logger.info("✅ CosyVoice-BlankEN downloaded")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️  CosyVoice-BlankEN not available: {e}")
        logger.info("   This is optional - the model will work without it")
        return False


def try_download_optional_ttsfrd(model_dir: str):
    """Try to download ttsfrd - OPTIONAL"""
    ttsfrd_path = os.path.join(model_dir, "CosyVoice-ttsfrd")

    if os.path.exists(ttsfrd_path):
        logger.info("✅ ttsfrd resource already exists")
        return ttsfrd_path

    try:
        from modelscope import snapshot_download
        logger.info("")
        logger.info("📦 Attempting to download CosyVoice-ttsfrd (optional)...")
        
        try:
            snapshot_download(
                model_id='iic/CosyVoice-ttsfrd',
                local_dir=ttsfrd_path,
                cache_dir=CACHE_DIR,
            )
        except TypeError:
            path = snapshot_download(
                model_id='iic/CosyVoice-ttsfrd',
                cache_dir=CACHE_DIR,
            )
            if os.path.exists(path) and path != ttsfrd_path:
                shutil.move(path, ttsfrd_path)
                
        logger.info("✅ ttsfrd resource downloaded")
        return ttsfrd_path
        
    except Exception as e:
        logger.warning(f"⚠️  ttsfrd not available: {e}")
        return None


if __name__ == "__main__":
    logger.info("🚀 Starting model download process")
    logger.info("")
    
    # Download main model (REQUIRED)
    model_path = download_cosyvoice2_model()
    
    # Try optional components (DON'T FAIL if unavailable)
    blanken_ok = try_download_optional_blanken(model_path)
    ttsfrd_path = try_download_optional_ttsfrd(os.path.dirname(model_path))
    
    logger.info("")
    logger.info("🎉 Setup complete!")
    logger.info(f"   Main Model: {model_path} ✅")
    logger.info(f"   BlankEN: {'✅' if blanken_ok else '⚠️  Not available (optional)'}")
    logger.info(f"   ttsfrd: {'✅' if ttsfrd_path else '⚠️  Not available (optional)'}")
    logger.info("")
    logger.info("Ready to start TTS service")