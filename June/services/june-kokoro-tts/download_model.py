#!/usr/bin/env python3
"""
Download Kokoro model script
"""
import os
import sys
from pathlib import Path

def download_kokoro_model():
    """Download Kokoro model if not already present"""
    model_dir = Path("/app/models")
    required_files = ["config.json", "pytorch_model.bin", "voices.bin"]
    
    # Check if model is already downloaded
    if all((model_dir / f).exists() and (model_dir / f).stat().st_size > 100 for f in required_files):
        print("✅ Kokoro model already present")
        return True
    
    print("📥 Downloading Kokoro-82M model...")
    try:
        from huggingface_hub import snapshot_download
        
        # Create directory
        model_dir.mkdir(parents=True, exist_ok=True)
        
        # Download model
        snapshot_download(
            repo_id="hexgrad/Kokoro-82M",
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
            cache_dir="/tmp/hf_cache"
        )
        
        # Verify download
        missing = []
        for f in required_files:
            file_path = model_dir / f
            if not file_path.exists() or file_path.stat().st_size < 100:
                missing.append(f)
        
        if missing:
            print(f"❌ Missing or empty files after download: {missing}")
            return False
            
        print("✅ Kokoro model downloaded successfully")
        print(f"📁 Model files: {list(model_dir.glob('*'))}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to download model: {e}")
        return False

if __name__ == "__main__":
    success = download_kokoro_model()
    if not success:
        print("⚠️ Model download failed, service will use fallback")
    sys.exit(0)  # Don't fail the build, let the service handle it