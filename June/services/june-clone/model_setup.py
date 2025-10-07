#!/usr/bin/env python3
"""
OpenVoice V2 Model Setup Script - CORRECTED
Downloads checkpoints from HuggingFace Hub
"""

import os
import sys
import json
import shutil
from pathlib import Path

def print_status(message, emoji="🔄"):
    """Print status with emoji"""
    print(f"{emoji} {message}", flush=True)

def main():
    """Download and setup OpenVoice V2 models"""
    try:
        print_status("Starting OpenVoice V2 model setup...")
        
        # Import after checking installation
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            print_status("Installing huggingface_hub...", "⚠️")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
            from huggingface_hub import snapshot_download
        
        # Configuration
        MODEL_ID = os.getenv("MODEL_ID", "myshell-ai/OpenVoiceV2")
        ROOT = Path(os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2"))
        CONVERTER_DIR = ROOT / "tone_color_converter"
        BASE_DIR = ROOT / "base_speakers"
        
        # Create directories
        print_status(f"Creating directories at {ROOT}...")
        CONVERTER_DIR.mkdir(parents=True, exist_ok=True)
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Download from HuggingFace
        print_status(f"Downloading from {MODEL_ID}...")
        
        # Patterns to download
        patterns = [
            "converter/*.pth",
            "converter/*.pt", 
            "converter/*.json",
            "base_speakers/*",
            "checkpoints_v2/*",
            "*.pth",
            "*.pt",
            "config.json"
        ]
        
        try:
            # Download to temporary directory first
            temp_dir = ROOT / "temp_download"
            temp_dir.mkdir(exist_ok=True)
            
            snapshot_download(
                repo_id=MODEL_ID,
                local_dir=str(temp_dir),
                local_dir_use_symlinks=False,
                allow_patterns=patterns,
                resume_download=True
            )
            
            print_status("Download completed, organizing files...")
            
            # Organize downloaded files
            # Look for converter files
            for pattern in ["*.pth", "*.pt"]:
                for file in temp_dir.rglob(pattern):
                    dest = CONVERTER_DIR / file.name
                    if not dest.exists():
                        shutil.copy2(file, dest)
                        print_status(f"Copied {file.name} to converter", "📦")
            
            # Look for config
            for config_file in temp_dir.rglob("config.json"):
                dest = CONVERTER_DIR / "config.json"
                if not dest.exists():
                    shutil.copy2(config_file, dest)
                    print_status("Copied config.json", "📦")
                    break
            
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        except Exception as e:
            print_status(f"Download failed: {e}", "⚠️")
            print_status("Creating minimal fallback configuration...", "⚠️")
        
        # Verify or create minimal config
        config_path = CONVERTER_DIR / "config.json"
        if not config_path.exists():
            print_status("Creating minimal config.json...")
            minimal_config = {
                "model": {
                    "type": "ToneColorConverter",
                    "hidden_channels": 192,
                    "filter_channels": 768,
                    "n_heads": 2,
                    "n_layers": 6,
                    "kernel_size": 3,
                    "p_dropout": 0.1
                }
            }
            with open(config_path, 'w') as f:
                json.dump(minimal_config, f, indent=2)
            print_status("Created minimal config", "✅")
        
        # Verify critical files
        print_status("Verifying setup...")
        
        missing = []
        if not config_path.exists():
            missing.append("config.json")
        
        checkpoint_files = list(CONVERTER_DIR.glob("*.pth")) + list(CONVERTER_DIR.glob("*.pt"))
        if not checkpoint_files:
            missing.append("checkpoint files (.pth or .pt)")
        
        if missing:
            print_status(f"⚠️ Missing: {', '.join(missing)}")
            print_status("Service may fail to start!", "⚠️")
            print_status("Checkpoint files must be manually provided", "ℹ️")
        else:
            print_status("All required files present!", "✅")
            
            # Show what we have
            print_status("Setup complete!", "🎉")
            print("\nInstalled files:")
            for item in CONVERTER_DIR.iterdir():
                if item.is_file():
                    size_mb = item.stat().st_size / (1024 * 1024)
                    print(f"  • {item.name} ({size_mb:.1f}MB)")
        
        return 0 if not missing else 1
        
    except Exception as e:
        print_status(f"Fatal error: {e}", "❌")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())