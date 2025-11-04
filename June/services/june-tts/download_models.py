#!/usr/bin/env python3
"""
CosyVoice2 Model Download Script
Downloads CosyVoice2-0.5B model from ModelScope with robust retries and git fallback
"""

import os
import logging
import shutil
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cosyvoice2-download")

MODEL_NAME = "CosyVoice2-0.5B"
MODEL_ID = f"iic/{MODEL_NAME}"
CACHE_ROOT = "/root/.cache/modelscope"
CACHE_DIR = "/tmp/modelscope_cache"


def _clean_incomplete(path: str):
    try:
        if os.path.exists(path):
            logger.info(f"   Cleaning incomplete directory: {path}")
            shutil.rmtree(path)
    except Exception as e:
        logger.warning(f"   Failed to clean {path}: {e}")


def _clean_modelscope_cache():
    for sub in ("ast_indexer", "hub", "blobs", "snapshots"):
        p = os.path.join(CACHE_ROOT, sub)
        if os.path.exists(p):
            try:
                logger.info(f"   Cleaning ModelScope cache: {p}")
                shutil.rmtree(p)
            except Exception as e:
                logger.warning(f"   Failed to clean cache {p}: {e}")


def _git_clone_fallback(target_dir: str) -> str:
    repo_url = f"https://www.modelscope.cn/{MODEL_ID}.git"
    logger.info("   Falling back to git LFS clone...")
    try:
        subprocess.run(["git", "lfs", "install"], check=True)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        subprocess.run(["git", "clone", repo_url, target_dir], check=True)
        logger.info(f"✅ Git clone completed into {target_dir}")
        return target_dir
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Git clone failed: {e}")
        raise


def _snapshot_download_robust(model_id: str, local_path: str) -> str:
    from modelscope import snapshot_download

    # Try new API (with local_dir), then legacy (without)
    try:
        logger.info("   Using ModelScope new API (local_dir)...")
        return snapshot_download(
            model_id=model_id,
            local_dir=local_path,
            cache_dir=CACHE_DIR,
            resume=True,
            timeout=600,
        )
    except TypeError as e:
        if "local_dir" not in str(e):
            raise
        logger.info("   Detected legacy ModelScope API; retrying without local_dir...")
        path = snapshot_download(
            model_id=model_id,
            cache_dir=CACHE_DIR,
            resume=True,
            timeout=600,
        )
        if os.path.exists(path) and path != local_path:
            if os.path.exists(local_path):
                shutil.rmtree(local_path)
            shutil.move(path, local_path)
        return local_path


def download_cosyvoice2_model():
    """Download CosyVoice2-0.5B model with retries and fallback."""
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    local_path = os.path.join(model_dir, MODEL_NAME)

    os.makedirs(model_dir, exist_ok=True)

    # If it looks already present, return
    if os.path.isdir(local_path):
        files = os.listdir(local_path)
        if len(files) > 5:
            logger.info(f"✅ Model already exists at {local_path} ({len(files)} files)")
            return local_path

    # Attempt 1: clean target and download
    try:
        logger.info(f"📦 Downloading {MODEL_NAME} from ModelScope...")
        logger.info(f"   Target directory: {local_path}")
        _clean_incomplete(local_path)
        return _snapshot_download_robust(MODEL_ID, local_path)
    except Exception as e:
        logger.error(f"❌ Attempt 1 failed: {e}")

    # Attempt 2: clean caches and retry
    try:
        logger.info("   Cleaning caches and retrying download (Attempt 2)...")
        _clean_incomplete(local_path)
        _clean_modelscope_cache()
        return _snapshot_download_robust(MODEL_ID, local_path)
    except Exception as e:
        logger.error(f"❌ Attempt 2 failed: {e}")

    # Attempt 3: git LFS fallback
    return _git_clone_fallback(local_path)


def download_ttsfrd_resource():
    """Optionally download CosyVoice-ttsfrd for better text normalization, with same robustness."""
    model_dir = os.getenv("MODEL_DIR", "/app/pretrained_models")
    ttsfrd_path = os.path.join(model_dir, "CosyVoice-ttsfrd")

    if os.path.exists(ttsfrd_path):
        logger.info(f"✅ ttsfrd resource already exists at {ttsfrd_path}")
        return ttsfrd_path

    try:
        from modelscope import snapshot_download
        logger.info("📦 Downloading CosyVoice-ttsfrd resource (optional)...")
        try:
            snapshot_download(
                model_id='iic/CosyVoice-ttsfrd',
                local_dir=ttsfrd_path,
                cache_dir=CACHE_DIR,
                resume=True,
                timeout=600,
            )
        except TypeError as e:
            if "local_dir" in str(e):
                path = snapshot_download(
                    model_id='iic/CosyVoice-ttsfrd',
                    cache_dir=CACHE_DIR,
                    resume=True,
                    timeout=600,
                )
                if os.path.exists(path) and path != ttsfrd_path:
                    if os.path.exists(ttsfrd_path):
                        shutil.rmtree(ttsfrd_path)
                    shutil.move(path, ttsfrd_path)
            else:
                raise
        logger.info(f"✅ ttsfrd resource downloaded to {ttsfrd_path}")
        return ttsfrd_path
    except Exception as e:
        logger.warning(f"⚠️ Failed to download ttsfrd resource (non-critical): {e}")
        # Fallback via git (optional)
        try:
            return _git_clone_fallback(ttsfrd_path)
        except Exception:
            return None


if __name__ == "__main__":
    logger.info("🚀 Starting CosyVoice2 model download")
    model_path = download_cosyvoice2_model()
    ttsfrd_path = download_ttsfrd_resource()
    logger.info("🎉 Model download complete!")
    logger.info(f"   Model: {model_path}")
    if ttsfrd_path:
        logger.info(f"   ttsfrd: {ttsfrd_path}")
    logger.info("   Ready for TTS synthesis")