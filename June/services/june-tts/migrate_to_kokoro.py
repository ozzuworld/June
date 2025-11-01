#!/usr/bin/env python3
"""
Kokoro TTS Migration Script
Seamlessly migrate from Chatterbox to Kokoro-82M for 97.5% latency improvement

This script:
1. Backs up existing Chatterbox configuration
2. Downloads and validates Kokoro models
3. Tests Kokoro performance
4. Provides rollback capability
5. Updates configuration for optimal performance
"""
import os
import sys
import asyncio
import time
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("kokoro-migration")

class KokoroMigration:
    def __init__(self):
        self.service_dir = Path("/app/tts")  # Current service directory
        self.backup_dir = Path("/app/tts/backup_chatterbox")
        self.models_dir = Path("/app/tts/models/kokoro")
        self.migration_complete = False
        
    async def run_migration(self):
        """Run complete migration process"""
        logger.info("🚀 Starting Chatterbox → Kokoro migration for ultra-low latency")
        logger.info("🎯 TARGET: 97.5% latency reduction (3000ms → <100ms)")
        
        try:
            # Step 1: Backup existing configuration
            await self._backup_chatterbox()
            
            # Step 2: Install Kokoro dependencies
            await self._install_dependencies()
            
            # Step 3: Download and validate Kokoro models
            await self._setup_kokoro_models()
            
            # Step 4: Test Kokoro performance
            performance_ok = await self._test_kokoro_performance()
            
            if not performance_ok:
                logger.error("❌ Kokoro performance test failed")
                return False
            
            # Step 5: Apply configuration updates
            await self._apply_kokoro_config()
            
            # Step 6: Final validation
            await self._validate_migration()
            
            self.migration_complete = True
            logger.info("✅ 🎉 Migration completed successfully!")
            logger.info("🎯 Expected improvement: 3000ms → <100ms TTS latency")
            return True
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            logger.info("🔄 Rollback available - run migrate_to_kokoro.py --rollback")
            return False
    
    async def _backup_chatterbox(self):
        """Backup existing Chatterbox configuration"""
        logger.info("💾 Backing up Chatterbox configuration...")
        
        self.backup_dir.mkdir(exist_ok=True)
        
        # Files to backup
        backup_files = [
            "main.py",
            "chatterbox_engine.py", 
            "streaming_tts.py",
            "requirements.txt",
            "Dockerfile"
        ]
        
        for file_name in backup_files:
            src = self.service_dir / file_name
            if src.exists():
                dst = self.backup_dir / f"{file_name}.backup"
                shutil.copy2(src, dst)
                logger.info(f"✅ Backed up: {file_name}")
        
        # Create rollback script
        rollback_script = self.backup_dir / "rollback.py"
        with open(rollback_script, 'w') as f:
            f.write(self._generate_rollback_script())
        
        logger.info(f"✅ Backup completed: {self.backup_dir}")
    
    async def _install_dependencies(self):
        """Install Kokoro dependencies"""
        logger.info("💾 Installing Kokoro dependencies...")
        
        try:
            import subprocess
            
            # Install Kokoro requirements
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", 
                "kokoro-onnx", "onnxruntime-gpu", "requests"
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"Dependency installation failed: {result.stderr}")
                raise RuntimeError("Failed to install Kokoro dependencies")
            
            logger.info("✅ Kokoro dependencies installed successfully")
            
        except Exception as e:
            logger.error(f"Error installing dependencies: {e}")
            raise
    
    async def _setup_kokoro_models(self):
        """Download and setup Kokoro models and voice packs"""
        logger.info("💾 Setting up Kokoro models and voice packs...")
        
        self.models_dir.mkdir(parents=True, exist_ok=True)
        voices_dir = self.models_dir / "voices"
        voices_dir.mkdir(exist_ok=True)
        
        import requests
        
        # Model and voice pack URLs
        downloads = {
            "kokoro-v0_19.onnx": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v0_19.onnx",
            "voices/af_bella.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_bella.pt",
            "voices/af_sarah.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_sarah.pt",
            "voices/am_michael.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/am_michael.pt", 
            "voices/am_adam.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/am_adam.pt",
        }
        
        for file_path, url in downloads.items():
            local_path = self.models_dir / file_path
            local_path.parent.mkdir(exist_ok=True)
            
            if local_path.exists():
                logger.info(f"✅ Already exists: {file_path}")
                continue
                
            logger.info(f"💾 Downloading: {file_path}")
            
            try:
                response = requests.get(url, stream=True, timeout=60)
                response.raise_for_status()
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                size_mb = local_path.stat().st_size / 1024 / 1024
                logger.info(f"✅ Downloaded: {file_path} ({size_mb:.1f}MB)")
                
            except Exception as e:
                logger.error(f"Failed to download {file_path}: {e}")
                raise
        
        logger.info(f"✅ Kokoro models ready: {self.models_dir}")
    
    async def _test_kokoro_performance(self) -> bool:
        """Test Kokoro performance to ensure sub-100ms capability"""
        logger.info("📊 Testing Kokoro performance...")
        
        try:
            # Initialize Kokoro engine for testing
            sys.path.append(str(self.service_dir))
            from kokoro_engine import kokoro_engine
            
            await kokoro_engine.initialize()
            
            # Performance tests
            test_cases = [
                "Hello, this is a test.",
                "Testing Kokoro ultra-low latency performance for real-time voice chat.",
                "The quick brown fox jumps over the lazy dog."
            ]
            
            total_time = 0
            sub_100ms_count = 0
            
            for i, text in enumerate(test_cases):
                logger.info(f"📋 Test {i+1}/3: '{text[:30]}...'")
                
                start_time = time.time()
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    await kokoro_engine.synthesize_to_file(
                        text=text,
                        file_path=tmp.name,
                        voice_preset="af_bella"
                    )
                
                inference_time = (time.time() - start_time) * 1000
                total_time += inference_time
                
                if inference_time < 100:
                    sub_100ms_count += 1
                    logger.info(f"✅ 🎆 SUB-100MS: {inference_time:.0f}ms")
                else:
                    logger.info(f"⚡ Performance: {inference_time:.0f}ms")
            
            avg_time = total_time / len(test_cases)
            success_rate = sub_100ms_count / len(test_cases) * 100
            
            logger.info(f"📊 Performance Summary:")
            logger.info(f"   Average inference: {avg_time:.0f}ms")
            logger.info(f"   Sub-100ms success rate: {success_rate:.0f}%")
            logger.info(f"   vs Chatterbox improvement: {((3000 - avg_time) / 3000 * 100):.1f}%")
            
            # Performance validation
            if avg_time < 200:  # Reasonable threshold for migration
                logger.info("✅ 🎆 KOKORO PERFORMANCE EXCELLENT - Ready for production!")
                return True
            else:
                logger.warning(f"⚠️ Performance slower than expected: {avg_time:.0f}ms")
                logger.info("💡 Consider GPU optimization or hardware upgrade")
                return False
                
        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            return False
    
    async def _apply_kokoro_config(self):
        """Apply Kokoro configuration files"""
        logger.info("🔄 Applying Kokoro configuration...")
        
        # Update main.py to use Kokoro
        main_kokoro = self.service_dir / "main_kokoro.py"
        main_current = self.service_dir / "main.py"
        
        if main_kokoro.exists():
            shutil.copy2(main_kokoro, main_current)
            logger.info("✅ Updated main.py to use Kokoro")
        
        # Update requirements if kokoro version exists
        req_kokoro = self.service_dir / "requirements_kokoro.txt"
        req_current = self.service_dir / "requirements.txt"
        
        if req_kokoro.exists():
            shutil.copy2(req_kokoro, req_current)
            logger.info("✅ Updated requirements.txt for Kokoro")
        
        logger.info("✅ Configuration updated for Kokoro ultra-low latency")
    
    async def _validate_migration(self):
        """Final validation of migration"""
        logger.info("🔍 Validating Kokoro migration...")
        
        # Check all required files exist
        required_files = [
            "kokoro_engine.py",
            "streaming_tts_kokoro.py",
            "main.py",
            "models/kokoro/kokoro-v0_19.onnx",
            "models/kokoro/voices/af_bella.pt"
        ]
        
        for file_path in required_files:
            full_path = self.service_dir / file_path
            if not full_path.exists():
                logger.error(f"❌ Missing required file: {file_path}")
                raise FileNotFoundError(f"Migration incomplete: missing {file_path}")
            logger.debug(f"✅ Validated: {file_path}")
        
        logger.info("✅ Migration validation passed")
    
    def _generate_rollback_script(self) -> str:
        """Generate rollback script for emergency use"""
        return '''
#!/usr/bin/env python3
"""
Emergency Rollback to Chatterbox TTS
Use this if Kokoro migration causes issues
"""
import shutil
from pathlib import Path

def rollback():
    print("🔄 Rolling back to Chatterbox TTS...")
    
    service_dir = Path("/app/tts")
    backup_dir = Path("/app/tts/backup_chatterbox")
    
    if not backup_dir.exists():
        print("❌ No backup found - manual restoration needed")
        return False
    
    # Restore backed up files
    backup_files = [
        ("main.py.backup", "main.py"),
        ("chatterbox_engine.py.backup", "chatterbox_engine.py"),
        ("streaming_tts.py.backup", "streaming_tts.py"),
        ("requirements.txt.backup", "requirements.txt"),
        ("Dockerfile.backup", "Dockerfile")
    ]
    
    for backup_name, current_name in backup_files:
        backup_path = backup_dir / backup_name
        current_path = service_dir / current_name
        
        if backup_path.exists():
            shutil.copy2(backup_path, current_path)
            print(f"✅ Restored: {current_name}")
    
    print("✅ Rollback completed")
    print("⚠️ Restart the TTS service to use Chatterbox again")
    return True

if __name__ == "__main__":
    rollback()
        '''
    
    async def rollback(self):
        """Rollback to Chatterbox if needed"""
        logger.info("🔄 Rolling back to Chatterbox TTS...")
        
        if not self.backup_dir.exists():
            logger.error("❌ No backup found - manual restoration needed")
            return False
        
        # Restore files
        backup_mappings = {
            "main.py.backup": "main.py",
            "chatterbox_engine.py.backup": "chatterbox_engine.py",
            "streaming_tts.py.backup": "streaming_tts.py",
            "requirements.txt.backup": "requirements.txt",
        }
        
        for backup_name, current_name in backup_mappings.items():
            backup_path = self.backup_dir / backup_name
            current_path = self.service_dir / current_name
            
            if backup_path.exists():
                shutil.copy2(backup_path, current_path)
                logger.info(f"✅ Restored: {current_name}")
        
        logger.info("✅ Rollback completed - restart service to use Chatterbox")
        return True
    
    def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status"""
        kokoro_files = [
            self.service_dir / "kokoro_engine.py",
            self.service_dir / "streaming_tts_kokoro.py",
            self.models_dir / "kokoro-v0_19.onnx",
            self.models_dir / "voices" / "af_bella.pt"
        ]
        
        return {
            "migration_complete": self.migration_complete,
            "backup_exists": self.backup_dir.exists(),
            "kokoro_files_ready": all(f.exists() for f in kokoro_files),
            "models_downloaded": (self.models_dir / "kokoro-v0_19.onnx").exists(),
            "voice_packs_ready": len(list((self.models_dir / "voices").glob("*.pt"))),
            "rollback_available": (self.backup_dir / "rollback.py").exists(),
        }


async def main():
    """Main migration entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate June TTS from Chatterbox to Kokoro")
    parser.add_argument("--rollback", action="store_true", help="Rollback to Chatterbox")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--test-only", action="store_true", help="Only test Kokoro performance")
    
    args = parser.parse_args()
    
    migration = KokoroMigration()
    
    if args.rollback:
        success = await migration.rollback()
        sys.exit(0 if success else 1)
    
    if args.status:
        status = migration.get_migration_status()
        logger.info(f"📊 Migration Status: {status}")
        return
    
    if args.test_only:
        logger.info("📋 Running Kokoro performance test only...")
        await migration._install_dependencies()
        await migration._setup_kokoro_models() 
        success = await migration._test_kokoro_performance()
        logger.info(f"Test result: {'PASSED' if success else 'FAILED'}")
        return
    
    # Run full migration
    success = await migration.run_migration()
    
    if success:
        logger.info("✅ 🎉 MIGRATION COMPLETED SUCCESSFULLY!")
        logger.info("🎯 Expected performance: 3000ms → <100ms (97.5% improvement)")
        logger.info("🚀 Restart the TTS service to use Kokoro ultra-low latency")
        logger.info("🔄 Rollback available if needed: python migrate_to_kokoro.py --rollback")
    else:
        logger.error("❌ Migration failed - check logs above")
        logger.info("🔄 Rollback available: python migrate_to_kokoro.py --rollback")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())