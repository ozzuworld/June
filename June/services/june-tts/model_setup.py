#!/usr/bin/env python3
"""
OpenVoice Model Setup Script
Downloads and organizes required model files for OpenVoice TTS system
"""

import os
import sys
import shutil
import zipfile
from pathlib import Path
from huggingface_hub import snapshot_download
import urllib.request
import traceback

def print_status(message, emoji="🔄"):
    """Print status message with emoji"""
    print(f"{emoji} {message}")

def download_file(url, destination):
    """Download file from URL with progress"""
    def progress_hook(block_num, block_size, total_size):
        if total_size > 0:
            downloaded = block_num * block_size
            percent = min(100, (downloaded * 100) // total_size)
            print(f"\rProgress: {percent}% ({downloaded // 1024 // 1024}MB/{total_size // 1024 // 1024}MB)", end="")
        sys.stdout.flush()
    
    urllib.request.urlretrieve(url, destination, reporthook=progress_hook)
    print()  # New line after progress

def main():
    """Main setup function"""
    try:
        print_status("Starting OpenVoice model setup...")
        
        # Configuration
        MODEL_ID = "myshell-ai/OpenVoiceV2"
        ROOT = Path("/models/openvoice")
        BASE = ROOT / "checkpoints_v2"
        CONV = ROOT / "checkpoints_v2" / "tone_color_converter"
        
        # Create directories
        print_status("Creating model directories...")
        BASE.mkdir(parents=True, exist_ok=True)
        CONV.mkdir(parents=True, exist_ok=True)
        
        # Download patterns for required files
        patterns = [
            'BASE_SPEAKERS/*',
            'TONE_COLOR_CONVERTER/*',
            'converter/*',
            'TONE_COLOR_CONVERTER_V2/*',
            'config.json',
            '*.pt',
            '*.pth',
            '*.json'
        ]
        
        print_status(f"📥 Downloading model files from {MODEL_ID}...")
        
        # Download from HuggingFace Hub
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=str(ROOT),
            local_dir_use_symlinks=False,
            allow_patterns=patterns,
            resume_download=True
        )
        
        print_status("✅ HuggingFace download completed!")
        
        # Download and extract checkpoints_v2_0417.zip as fallback/additional source
        checkpoint_url = "https://myshell-public-repo-hosting.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip"
        zip_path = ROOT / "checkpoints_v2_0417.zip"
        
        try:
            print_status("📥 Downloading checkpoints_v2_0417.zip...")
            download_file(checkpoint_url, zip_path)
            
            # Extract ZIP file
            print_status("📦 Extracting checkpoint files...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(ROOT)
            
            # Clean up ZIP file
            zip_path.unlink()
            print_status("✅ Checkpoint extraction completed!")
            
        except Exception as e:
            print_status(f"⚠️ Warning: Could not download checkpoints ZIP: {e}", "⚠️")
            print_status("Continuing with HuggingFace files...", "ℹ️")
        
        # Organize files - move converter files to proper location
        converter_source = ROOT / "checkpoints_v2" / "converter"
        if converter_source.exists():
            for file in converter_source.iterdir():
                if file.is_file() and file.suffix in ['.pth', '.pt', '.json']:
                    dest = CONV / file.name
                    if not dest.exists():
                        print_status(f"📁 Moving {file.name} to tone_color_converter/")
                        shutil.copy2(file, dest)
        
        # Also check for alternative directory structures
        alt_dirs = [
            ROOT / "TONE_COLOR_CONVERTER",
            ROOT / "TONE_COLOR_CONVERTER_V2", 
            ROOT / "tone_color_converter"
        ]
        
        for alt_dir in alt_dirs:
            if alt_dir.exists():
                print_status(f"📁 Found alternative directory: {alt_dir.name}")
                for file in alt_dir.rglob('*'):
                    if file.is_file() and file.suffix in ['.pth', '.pt', '.json']:
                        dest = CONV / file.name
                        if not dest.exists():
                            print_status(f"  📄 Copying {file.name}...")
                            shutil.copy2(file, dest)
                # Clean up alternative directory
                shutil.rmtree(alt_dir)
        
        # Move files from subdirectories to main checkpoints_v2
        for subdir in BASE.iterdir():
            if subdir.is_dir() and subdir.name not in ['tone_color_converter']:
                for file in subdir.rglob('*'):
                    if file.is_file():
                        dest = BASE / file.name
                        if not dest.exists():
                            print_status(f"📁 Moving {file.name} from {subdir.name}/")
                            shutil.move(str(file), str(dest))
        
        # Ensure required files exist
        for config_dir in BASE.rglob('*'):
            if config_dir.is_dir() and 'config.json' in [f.name for f in config_dir.iterdir()]:
                config_file = config_dir / 'config.json'
                dest = BASE / 'config.json'
                if not dest.exists():
                    print_status(f"📁 Copying config.json from {config_dir.name}/")
                    shutil.copy2(config_file, dest)
                    break
        
        # Copy checkpoint files to tone_color_converter
        for ckpt_file in BASE.rglob('*.pth'):
            if 'converter' in ckpt_file.name.lower() or 'checkpoint' in ckpt_file.name.lower():
                dest = CONV / ckpt_file.name
                if not dest.exists():
                    print_status(f"📁 Copying {ckpt_file.name} to tone_color_converter/")
                    shutil.copy2(ckpt_file, dest)
        
        # Verify installation
        config_path = BASE / 'config.json'
        checkpoint_files = list(CONV.glob('*.pth')) + list(CONV.glob('*.pt'))
        
        print_status("🔍 Verifying installation...")
        print_status(f"  Config file: {config_path.exists()}")
        print_status(f"  Checkpoint files: {len(checkpoint_files)} found")
        
        if config_path.exists():
            print_status("✅ Config file found!")
            for ckpt in checkpoint_files:
                print_status(f"  ✓ {ckpt.name}")
        
        if not config_path.exists():
            print_status("❌ ERROR: config.json not found in checkpoints_v2!", "❌")
            sys.exit(1)
        
        if not checkpoint_files:
            print_status("❌ ERROR: No checkpoint files found in tone_color_converter!", "❌")
            sys.exit(1)
        
        print_status("✅ Model setup completed successfully!")
        
    except Exception as e:
        print_status(f"❌ Fatal error during model setup: {e}", "❌")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()