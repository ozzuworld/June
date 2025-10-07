"""
Configuration for June TTS Service
"""

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings"""
    
    # Service settings
    service_name: str = "june-tts"
    version: str = "4.0.0"
    debug: bool = False
    
    # F5-TTS settings
    device: str = "auto"  # auto, cuda, cpu, mps
    model_cache_dir: str = "/tmp/f5tts_cache"
    
    # Audio settings
    sample_rate: int = 24000
    max_audio_length: int = 30  # seconds
    
    class Config:
        env_prefix = "JUNE_TTS_"

settings = Settings()
