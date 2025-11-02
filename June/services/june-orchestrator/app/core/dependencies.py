"""Dependency injection container - Phase 1 refactor"""
import logging
from functools import lru_cache
from typing import Optional

from ..config import config, AppConfig
from ..services.session.service import SessionService
from ..services.external.livekit import LiveKitClient

logger = logging.getLogger(__name__)

# Global instances (singleton pattern)
_session_service: Optional[SessionService] = None
_livekit_client: Optional[LiveKitClient] = None


@lru_cache()
def get_config() -> AppConfig:
    """Get application configuration"""
    return config


@lru_cache()
def get_livekit_client() -> LiveKitClient:
    """Get LiveKit client instance (singleton)"""
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
    """Get session service instance (singleton)"""
    global _session_service
    
    if _session_service is None:
        livekit_client = get_livekit_client()
        _session_service = SessionService(livekit_client=livekit_client)
        logger.info("✅ Session service singleton created")
    
    return _session_service


# FastAPI dependency functions (for use with Depends())
def session_service_dependency() -> SessionService:
    """FastAPI dependency for session service"""
    return get_session_service()


def livekit_client_dependency() -> LiveKitClient:
    """FastAPI dependency for LiveKit client"""
    return get_livekit_client()


def config_dependency() -> AppConfig:
    """FastAPI dependency for config"""
    return get_config()


# Cleanup function for testing
def reset_singletons():
    """Reset singleton instances (for testing)"""
    global _session_service, _livekit_client
    _session_service = None
    _livekit_client = None
    logger.info("🗑️ Singletons reset for testing")