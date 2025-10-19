# June/services/june-tts/config.py
"""
Configuration module for June TTS Service
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """TTS Service Configuration"""
    
    # LiveKit Configuration
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "")
    LIVEKIT_WS_URL: str = os.getenv("LIVEKIT_WS_URL", "wss://ozzu-livekit-serverless-5rbtbahf4a-ue.a.run.app")
    
    # TTS Configuration
    TTS_DEVICE: str = os.getenv("TTS_DEVICE", "auto")  # auto, cpu, cuda
    TTS_CACHE_DIR: str = os.getenv("TTS_CACHE_DIR", "/app/cache")
    VOICES_DIR: str = os.getenv("VOICES_DIR", "/app/voices")
    
    # Service Configuration
    SERVICE_PORT: int = int(os.getenv("SERVICE_PORT", "8000"))
    SERVICE_HOST: str = os.getenv("SERVICE_HOST", "0.0.0.0")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Voice Cloning Limits
    MAX_VOICE_FILES: int = int(os.getenv("MAX_VOICE_FILES", "10"))
    MAX_VOICE_DURATION: int = int(os.getenv("MAX_VOICE_DURATION", "300"))  # seconds
    MIN_VOICE_DURATION: float = float(os.getenv("MIN_VOICE_DURATION", "6.0"))  # seconds
    
    # Audio Processing
    TARGET_SAMPLE_RATE: int = 24000
    SUPPORTED_AUDIO_FORMATS: tuple = ('.wav', '.mp3', '.flac', '.m4a', '.mp4')
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        if not self.LIVEKIT_API_KEY:
            print("Warning: LIVEKIT_API_KEY not set")
        if not self.LIVEKIT_API_SECRET:
            print("Warning: LIVEKIT_API_SECRET not set")
    
    @property
    def is_livekit_configured(self) -> bool:
        """Check if LiveKit is properly configured"""
        return bool(self.LIVEKIT_API_KEY and self.LIVEKIT_API_SECRET and self.LIVEKIT_WS_URL)


# Global config instance
config = Config()