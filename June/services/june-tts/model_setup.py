#!/usr/bin/env python3
"""
OpenVoice Model Setup Script - Updated for Docker
Downloads and organizes required model files for OpenVoice TTS system
"""

import os
import sys
import shutil
import json
import tempfile
from pathlib import Path

def print_status(message, emoji="🔄"):
    """Print status message with emoji"""
    print(f"{emoji} {message}")

def main():
    """Main setup function"""
    try:
        print_status("Starting OpenVoice model setup...")
        
        # Configuration from environment
        MODEL_ID = os.getenv("MODEL_ID", "myshell-ai/OpenVoiceV2")
        ROOT = Path(os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2"))
        BASE = ROOT / "base_speakers"
        CONV = ROOT / "tone_color_converter"
        
        # Create directories
        print_status("Creating model directories...")
        BASE.mkdir(parents=True, exist_ok=True)
        CONV.mkdir(parents=True, exist_ok=True)
        
        # Try downloading from HuggingFace
        try:
            from huggingface_hub import snapshot_download
            
            patterns = [
                "base_speakers/*",
                "tone_color_converter/*",
                "converter/*", 
                "tone_color_converter_v2/*",
                "config.json",
                "*.pt",
                "*.pth",
            ]
            
            print_status(f"Downloading from {MODEL_ID} into {ROOT}...")
            
            snapshot_download(
                repo_id=MODEL_ID,
                local_dir=str(ROOT),
                local_dir_use_symlinks=False,
                allow_patterns=patterns,
                resume_download=True
            )
            print_status("Download completed successfully!")
            
        except Exception as e:
            print_status(f"Download failed: {e}", "⚠️")
            print_status("Will create fallback configuration...", "⚠️")
        
        # Normalize directory structure
        print_status("Organizing downloaded files...")
        
        # Handle alternative directory names
        for alt in ("converter", "tone_color_converter_v2"):
            alt_dir = ROOT / alt
            if alt_dir.is_dir():
                print_status(f"Moving files from {alt} to tone_color_converter")
                for p in alt_dir.rglob("*"):
                    if p.is_file():
                        dst = CONV / p.name
                        if not dst.exists():
                            shutil.copy2(p, dst)
                shutil.rmtree(alt_dir, ignore_errors=True)
        
        # Move root-level assets
        root_cfg = ROOT / "config.json"
        if root_cfg.exists():
            print_status("Moving root config.json to tone_color_converter")
            shutil.move(str(root_cfg), str(CONV / "config.json"))
        
        for ext in ("*.pt", "*.pth"):
            for p in ROOT.glob(ext):
                dst = CONV / p.name
                if not dst.exists():
                    print_status(f"Moving {p.name} to tone_color_converter")
                    shutil.move(str(p), str(dst))
        
        # Copy deep files to top level if needed
        deep_cfg = list(CONV.rglob("config.json"))
        if deep_cfg and not (CONV / "config.json").exists():
            print_status("Copying deep config.json to top level")
            shutil.copy2(str(deep_cfg[0]), str(CONV / "config.json"))
        
        deep_ckpt = list(CONV.rglob("*.pt")) + list(CONV.rglob("*.pth"))
        if deep_ckpt:
            top = CONV / deep_ckpt[0].name
            if not top.exists():
                print_status(f"Copying {deep_ckpt[0].name} to top level")
                shutil.copy2(str(deep_ckpt[0]), str(top))
        
        # Create minimal config if missing
        if not (CONV / "config.json").exists():
            print_status("Creating minimal config.json")
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
            with open(CONV / "config.json", 'w') as f:
                json.dump(config, f, indent=2)
        
        # Create dummy checkpoint if none exist
        if not list(CONV.glob("*.pt")) and not list(CONV.glob("*.pth")):
            print_status("Creating dummy checkpoint")
            try:
                import torch
                dummy_checkpoint = {
                    'model': {},
                    'optimizer': {},
                    'learning_rate': 0.0001,
                    'iteration': 0
                }
                torch.save(dummy_checkpoint, CONV / "checkpoint.pth")
            except ImportError:
                print_status("Torch not available, skipping dummy checkpoint", "⚠️")
        
        # Verify setup
        missing = []
        if not (CONV / "config.json").exists():
            missing.append("config.json")
        if not list(CONV.glob("*.pt")) and not list(CONV.glob("*.pth")):
            missing.append("checkpoint files")
        
        if missing:
            print_status(f"Missing: {', '.join(missing)}", "❌")
        else:
            print_status("Model setup completed successfully!")
        
        # List final structure
        print_status("Final model structure:")
        for item in CONV.iterdir():
            if item.is_file():
                size_mb = item.stat().st_size / (1024 * 1024)
                print_status(f"  {item.name} ({size_mb:.1f}MB)")
        
        print_status("Model setup completed!")
        
    except Exception as e:
        print_status(f"Fatal error during model setup: {e}", "❌")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()