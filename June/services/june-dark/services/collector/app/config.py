"""
Configuration for Collector Service
"""

from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    """Collector settings"""
    
    # Service info
    SERVICE_NAME: str = "june-collector"
    VERSION: str = "1.0.0"
    MODE: str = "day"  # day or night
    
    # Queue connections
    REDIS_URL: str
    RABBIT_URL: str
    
    # Storage
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    BUCKET_ARTIFACTS: str = "june-artifacts"
    
    # Orchestrator
    ORCHESTRATOR_URL: str = "http://orchestrator:8080"
    
    # Crawling settings
    CONCURRENT_REQUESTS: int = 8
    DOWNLOAD_DELAY: float = 1.0
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    # Limits
    MAX_DEPTH: int = 3
    MAX_PAGES_PER_DOMAIN: int = 100
    REQUEST_TIMEOUT: int = 30
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    
    # Screenshot settings
    SCREENSHOT_ENABLED: bool = True
    SCREENSHOT_QUALITY: int = 80
    SCREENSHOT_WIDTH: int = 1920
    SCREENSHOT_HEIGHT: int = 1080
    
    # Content extraction
    EXTRACT_TEXT: bool = True
    EXTRACT_IMAGES: bool = True
    EXTRACT_LINKS: bool = True
    EXTRACT_METADATA: bool = True
    
    # Proxy settings (optional)
    PROXY_ENABLED: bool = False
    PROXY_URL: Optional[str] = None
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()