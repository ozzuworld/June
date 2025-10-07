"""
Configuration module for the June TTS service.

Using Pydantic's `BaseSettings`, this module reads environment variables to
configure aspects of the service. Default values are provided for ease of
development, but you should set appropriate values in a `.env` file for
production deployments.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application configuration with sensible defaults."""
    
    # Allow extra fields from environment variables (Kubernetes env vars)
    model_config = {"extra": "allow"}

    # Paths to the model checkpoints. These values should point to directories
    # containing the OpenVoice V2 MeloTTS and ToneColorConverter checkpoints.
    melo_checkpoint: str = "checkpoints/melo_v2"
    converter_checkpoint: str = "checkpoints/converter_v2"

    # Maximum allowed upload size for reference audio (in bytes). The official
    # documentation recommends short, clean reference audio; this limit keeps
    # uploads manageable.
    max_file_size: int = 10 * 1024 * 1024  # 10 MB

    # Allowed audio file extensions for reference audio uploads.
    allowed_audio_formats: List[str] = ["wav", "mp3", "flac", "m4a"]

    # API key for simple authentication. Leave blank to disable auth.
    api_key: str = ""
    
    # Optional Kubernetes/deployment fields (with defaults)
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

    class Config:
        env_file = ".env"
        extra = "allow"  # This allows extra environment variables


settings = Settings()
