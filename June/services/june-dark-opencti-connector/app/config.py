"""
Configuration for June Dark OpenCTI Connector
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Connector settings"""

    # Connector identification
    CONNECTOR_ID: str = "june-dark-opencti-connector"
    CONNECTOR_NAME: str = "June Dark OSINT"
    CONNECTOR_SCOPE: str = "osint,threat-intelligence,enrichment"
    CONNECTOR_VERSION: str = "1.0.0"
    CONNECTOR_CONFIDENCE_LEVEL: int = 75
    CONNECTOR_LOG_LEVEL: str = "INFO"

    # OpenCTI connection
    OPENCTI_URL: str
    OPENCTI_TOKEN: str
    OPENCTI_SSL_VERIFY: bool = True

    # June Dark connections
    RABBITMQ_URL: str
    RABBITMQ_QUEUE: str = "enrichment.results"
    RABBITMQ_EXCHANGE: str = "june.enrichment"

    # Redis for state management
    REDIS_URL: Optional[str] = None

    # PostgreSQL for metadata (optional)
    POSTGRES_DSN: Optional[str] = None

    # Processing settings
    BATCH_SIZE: int = 10
    BATCH_TIMEOUT: int = 30
    MAX_TLP: str = "TLP:AMBER"

    # Indicator creation rules
    CREATE_INDICATORS: bool = True
    CREATE_OBSERVABLES: bool = True
    CREATE_NOTES: bool = True
    CREATE_REPORTS: bool = True

    # Entity mapping
    MAP_URLS_AS_OBSERVABLES: bool = True
    MAP_IPS_AS_OBSERVABLES: bool = True
    MAP_DOMAINS_AS_OBSERVABLES: bool = True
    MAP_EMAILS_AS_OBSERVABLES: bool = True
    MAP_ALERTS_AS_INCIDENTS: bool = True

    # Author and source
    AUTHOR_NAME: str = "June Dark OSINT Framework"
    SOURCE_NAME: str = "June Dark"

    # Performance
    WORKERS: int = 2
    PREFETCH_COUNT: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
