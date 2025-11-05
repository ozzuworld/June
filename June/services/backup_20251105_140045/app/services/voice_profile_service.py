"""Voice Profile Management Service

Manages user voice profiles, reference audio storage, and voice cloning integration
for skill-based demonstrations (like mockingbird skill).
"""
import os
import logging
import hashlib
import tempfile
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf
from fastapi import HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class VoiceProfile(BaseModel):
    """User voice profile model"""
    user_id: str
    voice_id: str  # Unique voice identifier
    name: str = "My Voice"
    language: str = "en"
    created_at: str
    updated_at: str
    reference_files: List[str] = []  # List of file paths
    total_duration_seconds: float = 0.0
    status: str = "active"  # active, processing, failed
    metadata: Dict[str, Any] = {}


class VoiceProfileService:
    """Service for managing voice profiles and skill-based cloning integration"""
    
    def __init__(self, storage_path: str = "/app/voice_profiles"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache of profiles
        self.profiles: Dict[str, VoiceProfile] = {}
        
        # Load existing profiles
        self._load_profiles()
        
        logger.info(f"📁 Voice profile storage: {self.storage_path}")
        logger.info(f"👥 Loaded {len(self.profiles)} voice profiles")
    
    def _load_profiles(self):
        """Load voice profiles from storage"""
        try:
            profile_file = self.storage_path / "profiles.json"
            
            if profile_file.exists():
                with open(profile_file, 'r') as f:
                    profiles_data = json.load(f)
                    
                for profile_data in profiles_data.values():
                    profile = VoiceProfile(**profile_data)
                    self.profiles[profile.user_id] = profile
                    
                logger.info(f"📂 Loaded {len(self.profiles)} profiles from storage")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load voice profiles: {e}")
    
    def _save_profiles(self):
        """Save voice profiles to storage"""
        try:
            profile_file = self.storage_path / "profiles.json"
            
            profiles_data = {}
            for user_id, profile in self.profiles.items():
                profiles_data[user_id] = profile.dict()
            
            with open(profile_file, 'w') as f:
                json.dump(profiles_data, f, indent=2)
                
            logger.debug(f"💾 Saved {len(self.profiles)} profiles to storage")
            
        except Exception as e:
            logger.error(f"❌ Failed to save voice profiles: {e}")
    
    def get_profile(self, user_id: str) -> Optional[VoiceProfile]:
        """Get voice profile for user"""
        return self.profiles.get(user_id)
    
    def has_profile(self, user_id: str) -> bool:
        """Check if user has a voice profile"""
        return user_id in self.profiles
    
    def list_profiles(self) -> List[VoiceProfile]:
        """List all voice profiles"""
        return list(self.profiles.values())
    
    async def create_profile_from_audio(
        self,
        user_id: str,
        audio_data: bytes,
        filename: str = None,
        language: str = "en"
    ) -> VoiceProfile:
        """Create voice profile from audio data (used by mockingbird skill)"""
        
        # Generate unique voice ID
        voice_id = hashlib.md5(f"{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        
        # Create user-specific directory
        user_dir = self.storage_path / user_id
        user_dir.mkdir(exist_ok=True)
        
        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mockingbird_{timestamp}.wav"
        
        file_path = user_dir / filename
        
        # Validate and save audio
        try:
            # Save to temp file first for validation
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            # Validate audio format
            audio, sr = sf.read(temp_path)
            duration = len(audio) / sr
            
            # Convert to mono if needed
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            
            # Resample to 24kHz if needed (june-tts v3.0.0 optimization)
            if sr != 24000:
                try:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sr, target_sr=24000)
                except ImportError:
                    from scipy import signal
                    num_samples = int(len(audio) * 24000 / sr)
                    audio = signal.resample(audio, num_samples)
            
            # Save normalized audio
            sf.write(str(file_path), audio, 24000)
            
            # Cleanup temp file
            os.unlink(temp_path)
            
            # Create or update profile
            now = datetime.now(timezone.utc).isoformat()
            
            if user_id in self.profiles:
                # Update existing profile
                profile = self.profiles[user_id]
                profile.reference_files.append(str(file_path))
                profile.total_duration_seconds += duration
                profile.updated_at = now
            else:
                # Create new profile
                profile = VoiceProfile(
                    user_id=user_id,
                    voice_id=voice_id,
                    name="Mockingbird Profile",
                    language=language,
                    created_at=now,
                    updated_at=now,
                    reference_files=[str(file_path)],
                    total_duration_seconds=duration,
                    status="active"
                )
                self.profiles[user_id] = profile
            
            self._save_profiles()
            
            logger.info(f"🎵 Created/updated voice profile for {user_id}: {duration:.1f}s")
            
            # Quality feedback
            if duration < 3.0:
                logger.warning(f"⚠️ Short reference audio: {duration:.1f}s (recommended: 6+ seconds)")
            elif duration >= 6.0:
                logger.info(f"✅ Good reference audio duration: {duration:.1f}s")
            
            return profile
            
        except Exception as e:
            logger.error(f"❌ Failed to process reference audio for {user_id}: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise HTTPException(status_code=422, detail=f"Invalid audio format: {e}")
    
    def get_user_references(self, user_id: str) -> List[str]:
        """Get reference audio files for user (compatible with june-tts v3.0.0)"""
        profile = self.profiles.get(user_id)
        if not profile:
            return []
        
        # Filter existing files
        existing_files = []
        for ref_file in profile.reference_files:
            if os.path.exists(ref_file):
                existing_files.append(ref_file)
            else:
                logger.warning(f"⚠️ Reference file missing: {ref_file}")
        
        return existing_files
    
    def clear_user_profile(self, user_id: str) -> bool:
        """Clear user's voice profile (for resetting mockingbird skill)"""
        if user_id not in self.profiles:
            return False
        
        profile = self.profiles[user_id]
        
        # Delete reference files
        for ref_file in profile.reference_files:
            try:
                if os.path.exists(ref_file):
                    os.unlink(ref_file)
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete {ref_file}: {e}")
        
        # Remove from memory and storage
        del self.profiles[user_id]
        self._save_profiles()
        
        logger.info(f"🗑️ Cleared voice profile for {user_id}")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get voice profile statistics"""
        total_profiles = len(self.profiles)
        total_duration = sum(p.total_duration_seconds for p in self.profiles.values())
        total_references = sum(len(p.reference_files) for p in self.profiles.values())
        
        return {
            "total_profiles": total_profiles,
            "total_references": total_references,
            "total_audio_duration_seconds": round(total_duration, 1),
            "avg_references_per_profile": round(total_references / total_profiles, 1) if total_profiles > 0 else 0,
            "profiles_by_language": self._get_language_distribution()
        }
    
    def _get_language_distribution(self) -> Dict[str, int]:
        """Get distribution of profiles by language"""
        distribution = {}
        for profile in self.profiles.values():
            lang = profile.language
            distribution[lang] = distribution.get(lang, 0) + 1
        return distribution


# Global voice profile service instance
voice_profile_service = VoiceProfileService()