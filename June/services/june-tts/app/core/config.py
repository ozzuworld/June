"""
Configuration module for the June TTS service.
"""

from pydantic_settings import BaseSettings
from typing import List
import torch


class Settings(BaseSettings):
    """Application configuration with sensible defaults."""

    model_config = {
        "extra": "allow",
        "env_file": ".env"
    }

    # Remove the problematic max_file_size field - just hardcode it for now
    # max_file_size: int = 20971520  # We'll handle this in the route validation

    # F5-TTS configuration
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Basic TTS settings
    allowed_audio_formats: List[str] = ["wav", "mp3", "flac", "m4a"]
    api_key: str = ""
    
    # Legacy fields (kept for compatibility but not used by F5-TTS)
    melo_checkpoint: str = "checkpoints/melo_v2"
    converter_checkpoint: str = "checkpoints/converter_v2"
    
    # Kubernetes environment variables (these ARE being set)
    service_name: str = "june-tts"
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    openvoice_checkpoints_v2: str = "/models/openvoice/checkpoints_v2"
    openvoice_device: str = "cuda"
    host_for_client: str = "127.0.0.1"
    melo_speaker_id: str = "0"
    melo_language: str = "EN"
    max_text_len: int = 2000
    cors_allow_origins: str = "*"
    log_level: str = "INFO"


settings = Settings()

# Hardcode file size limits for now
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
