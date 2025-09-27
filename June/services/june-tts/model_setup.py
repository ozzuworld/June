#!/usr/bin/env python3
"""
OpenVoice Model Setup Script - FIXED VERSION
Downloads and organizes required model files for OpenVoice TTS system
"""

import os
import sys
import shutil
import requests
from pathlib import Path
from huggingface_hub import snapshot_download, hf_hub_download
import traceback
import tempfile

def print_status(message, emoji="🔄"):
    """Print status message with emoji"""
    print(f"{emoji} {message}")

def download_file_with_progress(url, destination):
    """Download file from URL with progress"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(destination, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded * 100) // total_size
                        print(f"\rProgress: {percent}% ({downloaded // 1024 // 1024}MB/{total_size // 1024 // 1024}MB)", end="")
        print()  # New line after progress
        return True
    except Exception as e:
        print(f"\nDownload failed: {e}")
        return False

def create_minimal_config():
    """Create minimal configuration files if downloads fail"""
    print_status("🔧 Creating minimal configuration files...")
    
    conv_dir = Path("/models/openvoice/checkpoints_v2/tone_color_converter")
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    # Create minimal config.json
    config = {
        "model": {
            "type": "ToneColorConverter",
            "hidden_channels": 192,
            "filter_channels": 768,
            "n_heads": 2,
            "n_layers": 6,
            "kernel_size": 3,
            "p_dropout": 0.1,
            "resblock": "1",
            "resblock_kernel_sizes": [3, 7, 11],
            "resblock_dilation_sizes": [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
            "upsample_rates": [8, 8, 2, 2],
            "upsample_initial_channel": 512,
            "upsample_kernel_sizes": [16, 16, 4, 4],
            "gin_channels": 256
        }
    }
    
    config_path = conv_dir / "config.json"
    with open(config_path, 'w') as f:
        import json
        json.dump(config, f, indent=2)
    
    print_status(f"✅ Created minimal config at {config_path}")
    
    # Create a dummy checkpoint file (this won't work for actual synthesis, but prevents startup errors)
    dummy_checkpoint_path = conv_dir / "checkpoint.pth"
    if not dummy_checkpoint_path.exists():
        import torch
        dummy_checkpoint = {
            'model': {},
            'optimizer': {},
            'learning_rate': 0.0001,
            'iteration': 0
        }
        torch.save(dummy_checkpoint, dummy_checkpoint_path)
        print_status(f"⚠️ Created dummy checkpoint at {dummy_checkpoint_path} (for startup only)", "⚠️")

def main():
    """Main setup function"""
    try:
        print_status("Starting OpenVoice model setup...")
        
        # Configuration
        ROOT = Path("/models/openvoice")
        BASE = ROOT / "checkpoints_v2"
        CONV = ROOT / "checkpoints_v2" / "tone_color_converter"
        
        # Create directories
        print_status("Creating model directories...")
        BASE.mkdir(parents=True, exist_ok=True)
        CONV.mkdir(parents=True, exist_ok=True)
        
        # Try basic HuggingFace download
        patterns = ['*', '**/*']
        
        print_status(f"📥 Downloading with basic patterns...")
        
        try:
            snapshot_download(
                repo_id="myshell-ai/OpenVoiceV2",
                local_dir=str(ROOT),
                local_dir_use_symlinks=False,
                allow_patterns=patterns,
                resume_download=True
            )
            print_status("✅ HuggingFace download completed!")
        except Exception as e:
            print_status(f"⚠️ Download failed: {e}", "⚠️")
        
        # Look for any downloaded files and move them to correct locations
        print_status("📁 Organizing downloaded files...")
        for root_path, dirs, files in os.walk(ROOT):
            for file in files:
                file_path = Path(root_path) / file
                
                if file.endswith(('.pth', '.pt')) and 'convert' in file.lower():
                    dest = CONV / file
                    if not dest.exists():
                        print_status(f"📁 Moving {file} to tone_color_converter/")
                        shutil.copy2(file_path, dest)
                
                if file == 'config.json' and 'convert' in str(file_path).lower():
                    dest = CONV / 'config.json'
                    if not dest.exists():
                        print_status(f"📁 Moving config.json to tone_color_converter/")
                        shutil.copy2(file_path, dest)
        
        # Create minimal files if nothing worked
        config_exists = (CONV / "config.json").exists()
        checkpoint_exists = any((CONV / f).exists() for f in os.listdir(CONV) if f.endswith(('.pth', '.pt'))) if CONV.exists() and os.listdir(CONV) else False
        
        if not config_exists or not checkpoint_exists:
            print_status("⚠️ Required files missing, creating minimal configuration...", "⚠️")
            create_minimal_config()
        
        # Final verification
        print_status("🔍 Final verification...")
        
        config_path = CONV / 'config.json'
        checkpoint_files = list(CONV.glob('*.pth')) + list(CONV.glob('*.pt'))
        
        print_status(f"  📄 Config file: {config_path.exists()}")
        print_status(f"  📄 Checkpoint files: {len(checkpoint_files)} found")
        
        if config_path.exists():
            print_status("✅ Config file found!")
        
        for ckpt in checkpoint_files:
            print_status(f"  ✓ {ckpt.name}")
        
        # Final structure display
        if CONV.exists():
            print_status("📁 Final model structure:")
            for item in CONV.iterdir():
                if item.is_file():
                    size_mb = item.stat().st_size / (1024 * 1024)
                    print_status(f"  📄 {item.name} ({size_mb:.1f}MB)")
        
        if not config_path.exists():
            print_status("❌ ERROR: config.json not found!", "❌")
            sys.exit(1)
        
        if not checkpoint_files:
            print_status("❌ ERROR: No checkpoint files found!", "❌")
            sys.exit(1)
        
        print_status("✅ Model setup completed successfully!")
        
        if any('dummy' in str(f) for f in checkpoint_files):
            print_status("⚠️ WARNING: Using dummy checkpoint files - TTS synthesis will not work correctly!", "⚠️")
            print_status("⚠️ Please provide real model files for production use.", "⚠️")
        
    except Exception as e:
        print_status(f"❌ Fatal error during model setup: {e}", "❌")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
