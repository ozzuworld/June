"""Simplified dependency injection - Removed old TTSClient

CLEANED:
- Removed TTSClient (old implementation) 
- Using tts_service from tts_service.py instead
"""
import logging
from functools import lru_cache
from typing import Optional

from ..config import config, AppConfig
from ..services.session.service import SessionService
from ..services.external.livekit import LiveKitClient

logger = logging.getLogger(__name__)

# Global instances
_session_service: Optional[SessionService] = None
_livekit_client: Optional[LiveKitClient] = None


@lru_cache()
def get_config() -> AppConfig:
    return config


@lru_cache()
def get_livekit_client() -> LiveKitClient:
    global _livekit_client
    if _livekit_client is None:
        _livekit_client = LiveKitClient(
            api_key=config.livekit.api_key,
            api_secret=config.livekit.api_secret,
            ws_url=config.livekit.ws_url
        )
        logger.info("✅ LiveKit client singleton created")
    return _livekit_client


def get_session_service() -> SessionService:
    global _session_service
    if _session_service is None:
        _session_service = SessionService(livekit_client=get_livekit_client())
        logger.info("✅ Session service singleton created")
    return _session_service


# FastAPI dependency functions
def session_service_dependency() -> SessionService:
    return get_session_service()

def livekit_client_dependency() -> LiveKitClient:
    return get_livekit_client()

def config_dependency() -> AppConfig:
    return get_config()

def get_current_user():
    return {"sub": "user", "username": "june_user"}


# Cleanup for testing
def reset_singletons():
    global _session_service, _livekit_client
    _session_service = None
    _livekit_client = None
    logger.info("🗑️ Singletons reset")