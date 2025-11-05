#!/usr/bin/env python3
"""
CosyVoice2 Model Download Script - FIXED
Downloads CosyVoice2-0.5B model from ModelScope with robust retries
Fixed: Removed 'timeout' parameter that's not supported in older modelscope versions
"""

import os
import logging
import shutil
import subprocess
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
        "llm.pt",
        "flow.pt",
        "hift.pt"
    ]
    
    missing = []
    for file in critical_files:
        if not os.path.exists(os.path.join(model_path, file)):
            missing.append(file)
    
    return len(missing) == 0, missing


def _clean_directory(path: str):
    """Clean a directory if it exists"""
    try:
        if os.path.exists(path):
            logger.info(f"Cleaning directory: {path}")
            shutil.rmtree(path)
    except Exception as e:
        logger.warning(f"Failed to clean {path}: {e}")


def _git_clone_fallback(target_dir: str) -> str:
    """Fallback to git LFS clone"""
    repo_url = f"https://www.modelscope.cn/{MODEL_ID}.git"
    logger.info("=" * 60)
    logger.info("Attempting git LFS clone (fallback method)")
    logger.info("=" * 60)
    
    try:
        # Ensure git lfs is installed
        subprocess.run(["git", "lfs", "install"], check=True, capture_output=True)
        
        # Clean target
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        
        # Clone with progress
        logger.info(f"Cloning from: {repo_url}")
        logger.info(f"Target: {target_dir}")
        logger.info("This may take several minutes...")
        
        subprocess.run(
            ["git", "clone", "--progress", repo_url, target_dir],
            check=True
        )
        
        logger.info("✅ Git clone completed")
        return target_dir
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Git clone failed: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error during git clone: {e}")
        raise


def _modelscope_download(model_id: str, local_path: str) -> str:
    """Download using ModelScope SDK - FIXED VERSION"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        logger.error("❌ modelscope package not installed!")
        logger.error("   Install with: pip install modelscope")
        raise
    
    logger.info("=" * 60)
    logger.info("Downloading via ModelScope SDK")
    logger.info("=" * 60)
    logger.info(f"Model ID: {model_id}")
    logger.info(f"Target: {local_path}")
    logger.info("This may take 5-10 minutes depending on your connection...")
    logger.info("")
    
    # Try new API first (with local_dir parameter, WITHOUT timeout)
    try:
        return snapshot_download(
            model_id=model_id,
            local_dir=local_path,
            cache_dir=CACHE_DIR,
        )
    except TypeError as e:
        # Fallback to legacy API (without local_dir)
        if "local_dir" in str(e):
            logger.info("Using legacy ModelScope API...")
            path = snapshot_download(
                model_id=model_id,
                cache_dir=CACHE_DIR,
            )
            # Move to target location
            if os.path.exists(path) and path != local_path:
                if os.path.exists(local_path):
                    shutil.rmtree(local_path)
                shutil.move(path, local_path)
            return local_path
        raise


def download_blank_en_model(target_dir: str):
    """Download CosyVoice-BlankEN model (Qwen-based LLM) - FIXED"""
    blank_en_path = os.path.join(target_dir, "CosyVoice-BlankEN")
    
    # Check if already exists and has model files
    if os.path.exists(blank_en_path):
        model_files = ['config.json', 'pytorch_model.bin']
        has_files = all(os.path.exists(os.path.join(blank_en_path, f)) for f in model_files)
        if has_files:
            logger.info("✅ CosyVoice-BlankEN already exists")
            return
    
    try:
        from modelscope import snapshot_download
        logger.info("📦 Downloading CosyVoice-BlankEN (Qwen LLM)...")
        logger.info("   This is required for text processing")
        
        try:
            # FIXED: Removed timeout parameter
            snapshot_download(
                model_id='iic/CosyVoice-BlankEN',
                local_dir=blank_en_path,
                cache_dir=CACHE_DIR,
            )
        except TypeError:
            # FIXED: Removed timeout parameter
            path = snapshot_download(
                model_id='iic/CosyVoice-BlankEN',
                cache_dir=CACHE_DIR,
            )
            if os.path.exists(path) and path != blank_en_path:
                if os.path.exists(blank_en_path):
                    shutil.rmtree(blank_en_path)
                shutil.move(path, blank_en_path)
        
        logger.info("✅ CosyVoice-BlankEN downloaded")
        
    except Exception as e:
        logger.error(f"❌ Failed to download CosyVoice-BlankEN: {e}")
        logger.error("   This is required for the model to work!")
        raise


def download_cosyvoice2_model():
    """Download CosyVoice2-0.5B model with retries and verification"""
    
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
            logger.info(f"   Files: {file_count}")
            
            # Still need to check BlankEN even if main model exists
            download_blank_en_model(local_path)
            return local_path
        else:
            logger.warning(f"⚠️  Model exists but is incomplete")
            logger.warning(f"   Missing files: {', '.join(missing)}")
            logger.info("   Will re-download...")
    
    # Attempt 1: Clean download via ModelScope
    try:
        _clean_directory(local_path)
        result = _modelscope_download(MODEL_ID, local_path)
        
        # Verify download
        is_complete, missing = check_critical_files(result)
        if is_complete:
            file_count = len(os.listdir(result))
            logger.info("=" * 60)
            logger.info("✅ Download complete and verified")
            logger.info(f"   Location: {result}")
            logger.info(f"   Files: {file_count}")
            logger.info("=" * 60)
            
            # Download BlankEN model
            download_blank_en_model(result)
            return result
        else:
            raise Exception(f"Download incomplete. Missing files: {', '.join(missing)}")
            
    except Exception as e:
        logger.error(f"❌ ModelScope download failed: {e}")
        logger.info("")
    
    # Attempt 2: Clean caches and retry
    try:
        logger.info("Retrying with clean cache...")
        _clean_directory(local_path)
        _clean_directory(CACHE_DIR)
        
        result = _modelscope_download(MODEL_ID, local_path)
        
        is_complete, missing = check_critical_files(result)
        if is_complete:
            file_count = len(os.listdir(result))
            logger.info("=" * 60)
            logger.info("✅ Download complete and verified (retry succeeded)")
            logger.info(f"   Location: {result}")
            logger.info(f"   Files: {file_count}")
            logger.info("=" * 60)
            
            # Download BlankEN model
            download_blank_en_model(result)
            return result
        else:
            raise Exception(f"Download incomplete. Missing files: {', '.join(missing)}")
            
    except Exception as e:
        logger.error(f"❌ Retry failed: {e}")
        logger.info("")
    
    # Attempt 3: Git LFS fallback
    try:
        result = _git_clone_fallback(local_path)
        
        is_complete, missing = check_critical_files(result)
        if is_complete:
            logger.info("=" * 60)
            logger.info("✅ Git clone complete and verified")
            logger.info("=" * 60)
            
            # Download BlankEN model
            download_blank_en_model(result)
            return result
        else:
            raise Exception(f"Git clone incomplete. Missing files: {', '.join(missing)}")
            
    except Exception as e:
        logger.error(f"❌ All download methods failed!")
        logger.error(f"   Last error: {e}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  1. Check internet connection")
        logger.error("  2. Verify ModelScope is accessible from your region")
        logger.error("  3. Check disk space")
        logger.error("  4. Try manual download from: https://modelscope.cn/models/iic/CosyVoice2-0.5B")
        sys.exit(1)


def download_ttsfrd_resource():
    """Optionally download CosyVoice-ttsfrd for better text normalization - FIXED"""
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    ttsfrd_path = os.path.join(model_dir, "CosyVoice-ttsfrd")

    if os.path.exists(ttsfrd_path):
        logger.info(f"✅ ttsfrd resource already exists")
        return ttsfrd_path

    try:
        from modelscope import snapshot_download
        logger.info("📦 Downloading CosyVoice-ttsfrd (optional text normalization)...")
        
        try:
            # FIXED: Removed timeout parameter
            snapshot_download(
                model_id='iic/CosyVoice-ttsfrd',
                local_dir=ttsfrd_path,
                cache_dir=CACHE_DIR,
            )
        except TypeError:
            # FIXED: Removed timeout parameter
            path = snapshot_download(
                model_id='iic/CosyVoice-ttsfrd',
                cache_dir=CACHE_DIR,
            )
            if os.path.exists(path) and path != ttsfrd_path:
                if os.path.exists(ttsfrd_path):
                    shutil.rmtree(ttsfrd_path)
                shutil.move(path, ttsfrd_path)
                
        logger.info(f"✅ ttsfrd resource downloaded")
        return ttsfrd_path
        
    except Exception as e:
        logger.warning(f"⚠️  Failed to download ttsfrd (non-critical): {e}")
        return None


if __name__ == "__main__":
    logger.info("🚀 Starting model download process")
    logger.info("")
    
    model_path = download_cosyvoice2_model()
    ttsfrd_path = download_ttsfrd_resource()
    
    # Verify BlankEN exists
    blank_en_path = os.path.join(model_path, "CosyVoice-BlankEN")
    blank_en_ok = os.path.exists(os.path.join(blank_en_path, "config.json"))
    
    logger.info("")
    logger.info("🎉 Setup complete!")
    logger.info(f"   Model: {model_path}")
    logger.info(f"   BlankEN: {blank_en_path} {'✅' if blank_en_ok else '❌'}")
    if ttsfrd_path:
        logger.info(f"   ttsfrd: {ttsfrd_path}")
    logger.info("")
    logger.info("Ready to start TTS service")