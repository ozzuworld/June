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

    # Paths to the model checkpoints. These values should point to directories
    # containing the OpenVoice V2 MeloTTS and ToneColorConverter checkpoints.
    melo_checkpoint: str = "checkpoints/melo_v2"
    converter_checkpoint: str = "checkpoints/converter_v2"

    # Maximum allowed upload size for reference audio (in bytes). The official
    # documentation recommends short, clean reference audio; this limit keeps
    # uploads manageable.
    max_file_size: int = 10 * 1024 * 1024  # 10 MB

    # Allowed audio file extensions for reference audio uploads.
    allowed_audio_formats: List[str] = ["wav", "mp3", "flac", "m4a"]

    # API key for simple authentication. Leave blank to disable auth.
    api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()