"""
Configuration for Ops UI Service
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Ops UI settings"""
    
    # Service info
    SERVICE_NAME: str = "june-ops-ui"
    VERSION: str = "1.0.0"
    
    # Backend connections
    ELASTIC_URL: str
    REDIS_URL: str
    RABBIT_URL: str
    ORCHESTRATOR_URL: str
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()