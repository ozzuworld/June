"""
Configuration for Enricher Service
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Enricher settings"""
    
    # Service info
    SERVICE_NAME: str = "june-enricher"
    VERSION: str = "1.0.0"
    MODE: str = "day"
    
    # Database connections
    ELASTIC_URL: str
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str
    POSTGRES_DSN: str
    
    # Queue
    RABBIT_URL: str
    
    # Storage
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    BUCKET_ARTIFACTS: str = "june-artifacts"
    
    # Processing settings
    BATCH_SIZE: int = 10
    MAX_TEXT_LENGTH: int = 1000000  # 1MB
    
    # Alert thresholds
    ALERT_CONFIDENCE_THRESHOLD: float = 0.7
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()