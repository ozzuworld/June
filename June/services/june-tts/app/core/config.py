from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Keycloak Configuration
    keycloak_server_url: str = "http://localhost:8080/auth"
    keycloak_realm: str = "openvoice"
    keycloak_client_id: str = "openvoice-api"
    keycloak_client_secret: str
    
    # API Configuration
    api_title: str = "OpenVoice API"
    api_version: str = "1.0.0"
    debug: bool = False
    
    # OpenVoice Configuration
    checkpoints_path: str = "/workspace/OpenVoice/checkpoints_v2"
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    allowed_audio_formats: list[str] = ["wav", "mp3", "flac", "m4a"]
    
    # Performance
    max_concurrent_requests: int = 5
    request_timeout: int = 300  # 5 minutes
    
    class Config:
        env_file = ".env"

settings = Settings()
