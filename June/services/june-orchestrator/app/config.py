"""Configuration"""
import os
from typing import List
from pydantic import BaseModel


class ServiceConfig(BaseModel):
    """Service URLs"""
    tts_base_url: str
    stt_base_url: str
    gemini_api_key: str = ""


class AppConfig:
    """Main configuration"""
    
    def __init__(self):
        self.port = int(os.getenv("PORT", "8080"))
        self.host = os.getenv("HOST", "0.0.0.0")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # CORS
        cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
        self.cors_origins = [o.strip() for o in cors_origins.split(",")]
        
        # Janus Gateway URL (for admin API only)
        self.janus_url = os.getenv(
            "JANUS_URL",
            "http://june-janus.june-services.svc.cluster.local:8088"
        )
        
        # Service configuration
        self.services = self._load_service_config()
    
    def _load_service_config(self) -> ServiceConfig:
        return ServiceConfig(
            tts_base_url=os.getenv(
                "TTS_SERVICE_URL",
                "http://june-tts.june-services.svc.cluster.local:8000"
            ),
            stt_base_url=os.getenv(
                "STT_SERVICE_URL",
                "http://june-stt.june-services.svc.cluster.local:8080"
            ),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "")
        )


config = AppConfig()