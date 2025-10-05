"""
Configuration management for June Orchestrator
"""
import os
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def get_config():
    """Get application configuration (cached)"""
    return {
        "service_name": os.getenv("SERVICE_NAME", "june-orchestrator"),
        "port": int(os.getenv("PORT", "8080")),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        
        # AI Configuration
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        
        # Service URLs (from K8s secrets/config)
        "tts_base_url": os.getenv("TTS_BASE_URL", "https://tts.allsafe.world"),
        
        # Auth Configuration (from K8s secrets)
        "keycloak_url": os.getenv("KEYCLOAK_URL", ""),
        "keycloak_realm": os.getenv("KEYCLOAK_REALM", "allsafe"),
        
        # Service Token (from K8s secret)
        "stt_service_token": os.getenv("STT_SERVICE_TOKEN", ""),
        
        # CORS
        "cors_origins": os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    }


def is_production() -> bool:
    """Check if running in production"""
    return os.getenv("ENVIRONMENT", "development") == "production"


def get_gemini_api_key() -> Optional[str]:
    """Get Gemini API key with validation"""
    key = get_config()["gemini_api_key"]
    return key if key and len(key) > 30 else None