"""
Configuration module for the June TTS service.

Using Pydantic's `BaseSettings`, this module reads environment variables to
configure aspects of the service. Default values are provided for ease of
development, but you should set appropriate values in a `.env` file for
production deployments.
"""

from pydantic_settings import BaseSettings
from typing import List
import torch
import os


def parse_max_file_size() -> int:
    """Parse MAX_FILE_SIZE environment variable, handling shell expressions"""
    env_val = os.getenv("MAX_FILE_SIZE", "10485760")  # 10MB default
    
    # Handle shell arithmetic like '$((20*1024*1024))'
    if env_val.startswith('$((') and env_val.endswith('))'):
        try:
            # Extract the arithmetic expression
            expr = env_val[3:-2]  # Remove '$((...))'
            # Simple eval for basic arithmetic (safe for deployment env)
            return eval(expr)
        except:
            return 10485760  # Fallback to 10MB
    
    try:
        return int(env_val)
    except:
        return 10485760  # Fallback to 10MB


class Settings(BaseSettings):
    """Application configuration with sensible defaults."""

    # Use Pydantic v2 model_config
    model_config = {
        "extra": "allow",
        "env_file": ".env"
    }

    # Paths to the model checkpoints (keeping for compatibility)
    melo_checkpoint: str = "checkpoints/melo_v2"
    converter_checkpoint: str = "checkpoints/converter_v2"

    # Maximum allowed upload size - parse from environment properly
    max_file_size: int = parse_max_file_size()

    # Allowed audio file extensions for reference audio uploads
    allowed_audio_formats: List[str] = ["wav", "mp3", "flac", "m4a"]

    # API key for simple authentication. Leave blank to disable auth.
    api_key: str = ""

    # F5-TTS device configuration
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    
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


settings = Settings()
