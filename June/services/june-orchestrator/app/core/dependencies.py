"""Dependency injection container - Phase 2 enhanced"""
import logging
from functools import lru_cache
from typing import Optional

from ..config import config, AppConfig
from ..services.session.service import SessionService
from ..services.external.livekit import LiveKitClient
from ..services.external.tts import TTSClient
from ..services.conversation.processor import ConversationProcessor
from ..services.conversation.security_guard import SecurityGuard
from ..services.conversation.tts_orchestrator import TTSOrchestrator

logger = logging.getLogger(__name__)

# Global instances (singleton pattern)
_session_service: Optional[SessionService] = None
_livekit_client: Optional[LiveKitClient] = None
_tts_client: Optional[TTSClient] = None
_security_guard: Optional[SecurityGuard] = None
_tts_orchestrator: Optional[TTSOrchestrator] = None
_conversation_processor: Optional[ConversationProcessor] = None


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


@lru_cache()
def get_tts_client() -> TTSClient:
    """Get TTS client instance (singleton)"""
    global _tts_client
    
    if _tts_client is None:
        _tts_client = TTSClient(
            base_url=config.services.tts_base_url,
            timeout=30.0
        )
        logger.info("✅ TTS client singleton created")
    
    return _tts_client


def get_session_service() -> SessionService:
    """Get session service instance (singleton)"""
    global _session_service
    
    if _session_service is None:
        livekit_client = get_livekit_client()
        _session_service = SessionService(livekit_client=livekit_client)
        logger.info("✅ Session service singleton created")
    
    return _session_service


def get_security_guard() -> SecurityGuard:
    """Get security guard instance (singleton)"""
    global _security_guard
    
    if _security_guard is None:
        # Import here to avoid circular imports
        from ..security.rate_limiter import rate_limiter, duplication_detector
        from ..security.cost_tracker import circuit_breaker
        
        _security_guard = SecurityGuard(
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            duplication_detector=duplication_detector
        )
        logger.info("✅ Security guard singleton created")
    
    return _security_guard


def get_tts_orchestrator() -> TTSOrchestrator:
    """Get TTS orchestrator instance (singleton)"""
    global _tts_orchestrator
    
    if _tts_orchestrator is None:
        # Import here to avoid circular imports
        from ..services.voice_profile_service import voice_profile_service
        
        _tts_orchestrator = TTSOrchestrator(
            tts_base_url=config.services.tts_base_url,
            voice_profile_service=voice_profile_service
        )
        logger.info("✅ TTS orchestrator singleton created")
    
    return _tts_orchestrator


def get_conversation_processor() -> ConversationProcessor:
    """Get conversation processor instance (singleton) - Phase 2"""
    global _conversation_processor
    
    if _conversation_processor is None:
        # Import here to avoid circular imports
        from ..services.ai_service import generate_response
        from ..services.streaming_service import streaming_ai_service
        from ..services.skill_service import skill_service
        from ..security.cost_tracker import call_tracker
        
        _conversation_processor = ConversationProcessor(
            session_service=get_session_service(),
            security_guard=get_security_guard(),
            tts_orchestrator=get_tts_orchestrator(),
            ai_service=generate_response,  # Pass the function
            streaming_ai_service=streaming_ai_service,
            skill_service=skill_service,
            cost_tracker=call_tracker,
            config=config
        )
        logger.info("✅ Conversation processor singleton created (Phase 2)")
    
    return _conversation_processor


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


def conversation_processor_dependency() -> ConversationProcessor:
    """FastAPI dependency for conversation processor - Phase 2"""
    return get_conversation_processor()


def security_guard_dependency() -> SecurityGuard:
    """FastAPI dependency for security guard"""
    return get_security_guard()


def tts_orchestrator_dependency() -> TTSOrchestrator:
    """FastAPI dependency for TTS orchestrator"""
    return get_tts_orchestrator()


# Cleanup function for testing
def reset_singletons():
    """Reset singleton instances (for testing)"""
    global _session_service, _livekit_client, _tts_client, _security_guard
    global _tts_orchestrator, _conversation_processor
    
    _session_service = None
    _livekit_client = None
    _tts_client = None
    _security_guard = None
    _tts_orchestrator = None
    _conversation_processor = None
    
    logger.info("🗑️ Singletons reset for testing")