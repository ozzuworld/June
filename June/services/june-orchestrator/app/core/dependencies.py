"""Simplified dependency injection - Removed old TTSClient

CLEANED:
- Removed TTSClient (old implementation) 
- Using tts_service from tts_service.py instead
- Added ConversationManager for participant tracking
"""
import logging
from functools import lru_cache
from typing import Optional

from ..config import config, AppConfig
from ..services.session.service import SessionService
from ..services.external.livekit import LiveKitClient
from ..services.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

# Global instances
_session_service: Optional[SessionService] = None
_livekit_client: Optional[LiveKitClient] = None
_conversation_manager: Optional[ConversationManager] = None


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


def get_conversation_manager() -> ConversationManager:
    """Get or create conversation manager singleton"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
        logger.info("✅ Conversation manager singleton created")
    return _conversation_manager


# FastAPI dependency functions
def session_service_dependency() -> SessionService:
    return get_session_service()

def livekit_client_dependency() -> LiveKitClient:
    return get_livekit_client()

def conversation_manager_dependency() -> ConversationManager:
    return get_conversation_manager()

def config_dependency() -> AppConfig:
    return get_config()

def get_current_user():
    return {"sub": "user", "username": "june_user"}


# Cleanup for testing
def reset_singletons():
    global _session_service, _livekit_client, _conversation_manager
    _session_service = None
    _livekit_client = None
    _conversation_manager = None
    logger.info("🗑️ Singletons reset")