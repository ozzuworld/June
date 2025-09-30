"""
Configuration settings for June Dark Orchestrator
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Service configuration
    SERVICE_NAME: str = "june-orchestrator"
    VERSION: str = "1.0.0"
    MODE: str = "day"  # 'day' or 'night'
    
    # Database connections
    POSTGRES_DSN: str
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str
    ELASTIC_URL: str
    REDIS_URL: str
    
    # Message queue
    RABBIT_URL: str
    
    # Object storage
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    BUCKET_ARTIFACTS: str = "june-artifacts"
    
    # API configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080
    WORKERS: int = 2
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # Feature flags
    FEATURE_OPENCTI: bool = False
    FEATURE_DARK_WEB: bool = False
    FEATURE_MALWARE_ANALYSIS: bool = False
    FEATURE_SOCIAL_API: bool = False
    FEATURE_CT_LOGS: bool = False
    FEATURE_GRAPH_ML: bool = False
    
    # Security
    ORCHESTRATOR_API_KEY: Optional[str] = None
    JWT_SECRET: Optional[str] = None
    JWT_EXPIRY_HOURS: int = 24
    
    # Performance tuning
    ORCHESTRATOR_WORKERS: int = 2
    POSTGRES_POOL_SIZE: int = 20
    NEO4J_POOL_SIZE: int = 50
    REDIS_POOL_SIZE: int = 10
    
    # Scheduler settings
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()