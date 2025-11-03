"""Dependency injection container - Phase 2 enhanced + Natural Conversation integration"""
import logging
import redis.asyncio as redis
from functools import lru_cache
from typing import Optional

from ..config import config, AppConfig
from ..services.session.service import SessionService
from ..services.external.livekit import LiveKitClient
from ..services.external.tts import TTSClient
from ..services.conversation.processor import ConversationProcessor
from ..services.conversation.security_guard import SecurityGuard
from ..services.conversation.tts_orchestrator import TTSOrchestrator
# Conversational AI imports (existing)
from ..services.conversation_memory_service import ConversationMemoryService
from ..services.conversational_ai_processor import ConversationalAIProcessor
# NEW imports
from ..services.enhanced_conversation_memory import EnhancedConversationMemoryService
from ..services.natural_conversation_processor import NaturalConversationProcessor
from ..services.emotion_intelligence_service import EmotionIntelligenceService

logger = logging.getLogger(__name__)

# Global instances (singleton pattern)
_session_service: Optional[SessionService] = None
_livekit_client: Optional[LiveKitClient] = None
_tts_client: Optional[TTSClient] = None
_security_guard: Optional[SecurityGuard] = None
_tts_orchestrator: Optional[TTSOrchestrator] = None
_conversation_processor: Optional[ConversationProcessor] = None
# Conversational AI singletons (existing)
_redis_client: Optional[redis.Redis] = None
_conversation_memory_service: Optional[ConversationMemoryService] = None
_conversational_ai_processor: Optional[ConversationalAIProcessor] = None
# NEW singletons
_enhanced_memory_service: Optional[EnhancedConversationMemoryService] = None
_natural_conversation_processor: Optional[NaturalConversationProcessor] = None
_emotion_service: Optional[EmotionIntelligenceService] = None


@lru_cache()
def get_config() -> AppConfig:
    return config


@lru_cache()
def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            password=config.redis.password if config.redis.password else None,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info(f"✅ Redis client singleton created: {config.redis.host}:{config.redis.port}/{config.redis.db}")
    return _redis_client


@lru_cache()
def get_conversation_memory_service() -> ConversationMemoryService:
    global _conversation_memory_service
    if _conversation_memory_service is None:
        _conversation_memory_service = ConversationMemoryService(get_redis_client())
        logger.info("✅ Conversation memory service singleton created")
    return _conversation_memory_service


@lru_cache()
def get_conversational_ai_processor() -> ConversationalAIProcessor:
    global _conversational_ai_processor
    if _conversational_ai_processor is None:
        _conversational_ai_processor = ConversationalAIProcessor(
            memory_service=get_conversation_memory_service(),
            config=config
        )
        logger.info("✅ Conversational AI processor singleton created")
    return _conversational_ai_processor


# NEW providers
@lru_cache()
def get_enhanced_memory_service() -> EnhancedConversationMemoryService:
    global _enhanced_memory_service
    if _enhanced_memory_service is None:
        _enhanced_memory_service = EnhancedConversationMemoryService(get_redis_client())
        logger.info("✅ Enhanced conversation memory service singleton created")
    return _enhanced_memory_service


@lru_cache()
def get_emotion_service() -> EmotionIntelligenceService:
    global _emotion_service
    if _emotion_service is None:
        _emotion_service = EmotionIntelligenceService(get_redis_client())
        logger.info("✅ Emotion intelligence service singleton created")
    return _emotion_service


@lru_cache()
def get_natural_conversation_processor() -> NaturalConversationProcessor:
    global _natural_conversation_processor
    if _natural_conversation_processor is None:
        from ..services.ai_service import generate_response
        _natural_conversation_processor = NaturalConversationProcessor(
            enhanced_memory_service=get_enhanced_memory_service(),
            ai_service=generate_response,
            config=config
        )
        logger.info("✅ Natural conversation processor singleton created")
    return _natural_conversation_processor


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


@lru_cache()
def get_tts_client() -> TTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient(
            base_url=config.services.tts_base_url,
            timeout=30.0
        )
        logger.info("✅ TTS client singleton created")
    return _tts_client


def get_session_service() -> SessionService:
    global _session_service
    if _session_service is None:
        _session_service = SessionService(livekit_client=get_livekit_client())
        logger.info("✅ Session service singleton created")
    return _session_service


def get_security_guard() -> SecurityGuard:
    global _security_guard
    if _security_guard is None:
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
    global _tts_orchestrator
    if _tts_orchestrator is None:
        from ..services.voice_profile_service import voice_profile_service
        _tts_orchestrator = TTSOrchestrator(
            tts_base_url=config.services.tts_base_url,
            voice_profile_service=voice_profile_service
        )
        logger.info("✅ TTS orchestrator singleton created")
    return _tts_orchestrator


def get_conversation_processor() -> ConversationProcessor:
    global _conversation_processor
    if _conversation_processor is None:
        from ..services.ai_service import generate_response
        from ..services.streaming_service import streaming_ai_service
        from ..services.skill_service import skill_service
        from ..security.cost_tracker import call_tracker
        _conversation_processor = ConversationProcessor(
            session_service=get_session_service(),
            security_guard=get_security_guard(),
            tts_orchestrator=get_tts_orchestrator(),
            ai_service=generate_response,
            streaming_ai_service=streaming_ai_service,
            skill_service=skill_service,
            cost_tracker=call_tracker,
            config=config
        )
        logger.info("✅ Conversation processor singleton created (Phase 2)")
    return _conversation_processor


# FastAPI dependency functions (for use with Depends())

def session_service_dependency() -> SessionService:
    return get_session_service()

def livekit_client_dependency() -> LiveKitClient:
    return get_livekit_client()

def config_dependency() -> AppConfig:
    return get_config()

def redis_client_dependency() -> redis.Redis:
    return get_redis_client()

def conversation_memory_service_dependency() -> ConversationMemoryService:
    return get_conversation_memory_service()

def conversational_ai_processor_dependency() -> ConversationalAIProcessor:
    return get_conversational_ai_processor()

def conversation_processor_dependency() -> ConversationProcessor:
    return get_conversation_processor()

def security_guard_dependency() -> SecurityGuard:
    return get_security_guard()

def tts_orchestrator_dependency() -> TTSOrchestrator:
    return get_tts_orchestrator()

# NEW FastAPI dependencies

def enhanced_memory_service_dependency() -> EnhancedConversationMemoryService:
    return get_enhanced_memory_service()

def natural_conversation_processor_dependency() -> NaturalConversationProcessor:
    return get_natural_conversation_processor()

def emotion_service_dependency() -> EmotionIntelligenceService:
    return get_emotion_service()


# Simple authentication dependency

def get_current_user():
    return {"sub": "user", "username": "june_user"}


# Cleanup function for testing

def reset_singletons():
    global _session_service, _livekit_client, _tts_client, _security_guard
    global _tts_orchestrator, _conversation_processor
    global _redis_client, _conversation_memory_service, _conversational_ai_processor
    global _enhanced_memory_service, _natural_conversation_processor, _emotion_service
    _session_service = None
    _livekit_client = None
    _tts_client = None
    _security_guard = None
    _tts_orchestrator = None
    _conversation_processor = None
    _redis_client = None
    _conversation_memory_service = None
    _conversational_ai_processor = None
    _enhanced_memory_service = None
    _natural_conversation_processor = None
    _emotion_service = None
    logger.info("🗑️ All singletons reset for testing")
