import os
from typing import Optional
from pydantic import BaseSettings

class Settings(BaseSettings):
    """Configuration settings for June Dark OSINT Framework"""
    
    # Service Configuration
    SERVICE_NAME: str = "june-dark"
    VERSION: str = "2.0.0"
    DEBUG: bool = False
    
    # YOLO Configuration
    YOLO_MODEL_SIZE: str = "small"  # nano, small, medium, large, extra_large
    YOLO_CONFIDENCE: float = 0.4
    YOLO_IOU_THRESHOLD: float = 0.7
    YOLO_MAX_DETECTIONS: int = 100
    
    # OpenCTI Configuration
    OPENCTI_URL: Optional[str] = None
    OPENCTI_TOKEN: Optional[str] = None
    OPENCTI_SSL_VERIFY: bool = True
    
    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600
    
    # RabbitMQ Configuration
    RABBIT_URL: str = "amqp://guest:guest@localhost:5672//"
    
    # GPU Configuration
    CUDA_VISIBLE_DEVICES: str = "0"
    GPU_MEMORY_FRACTION: float = 0.8
    
    # Processing Configuration
    MAX_BATCH_SIZE: int = 20
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    SUPPORTED_FORMATS: list = ["jpg", "jpeg", "png", "bmp", "tiff"]
    
    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    class Config:
        env_file = ".env"
        case_sensitive = True