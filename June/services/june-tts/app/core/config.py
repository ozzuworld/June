from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application configuration with sensible defaults."""
    
    model_config = {"extra": "allow"}  # Allow Kubernetes env vars
    
    # Basic config
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    allowed_audio_formats: list[str] = ["wav", "mp3", "flac", "m4a"]
    api_key: str = ""
    
    # XTTS device
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    
    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
