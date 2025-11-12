"""
Simple Assistant Service Module
Provides global access to the SimpleVoiceAssistant
"""
import logging
from typing import Optional
from .simple_voice_assistant import SimpleVoiceAssistant
from .tts_service import tts_service
from ..config import config

logger = logging.getLogger(__name__)

# Global assistant instance
_global_assistant: Optional[SimpleVoiceAssistant] = None


def initialize_assistant() -> SimpleVoiceAssistant:
    """Initialize the global assistant instance"""
    global _global_assistant
    
    if _global_assistant is None:
        logger.info("=" * 80)
        logger.info("🚀 Initializing Simple Voice Assistant...")
        
        # Validate Gemini configuration
        if not config.services.gemini_api_key:
            logger.error("❌ GEMINI_API_KEY not configured!")
            raise ValueError("GEMINI_API_KEY must be set in environment")
        
        # Validate LiveKit configuration
        if not config.livekit.ws_url:
            logger.error("❌ LIVEKIT_WS_URL not configured!")
            raise ValueError("LIVEKIT_WS_URL must be set in environment")
        
        if not config.livekit.api_key or not config.livekit.api_secret:
            logger.error("❌ LIVEKIT credentials not configured!")
            raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in environment")
        
        logger.info(f"✅ Gemini API key configured")
        logger.info(f"✅ TTS service: {config.services.tts_base_url}")
        logger.info(f"✅ LiveKit URL: {config.livekit.ws_url}")
        
        # Create assistant with LiveKit credentials
        _global_assistant = SimpleVoiceAssistant(
            gemini_api_key=config.services.gemini_api_key,
            tts_service=tts_service,
            livekit_url=config.livekit.ws_url,
            livekit_api_key=config.livekit.api_key,
            livekit_api_secret=config.livekit.api_secret
        )
        
        logger.info("✅ Simple Voice Assistant initialized")
        logger.info("=" * 80)
    
    return _global_assistant


def get_assistant() -> SimpleVoiceAssistant:
    """Get the global assistant instance"""
    if _global_assistant is None:
        return initialize_assistant()
    return _global_assistant


# Reset for testing
def reset_assistant():
    """Reset the global assistant (for testing only)"""
    global _global_assistant
    _global_assistant = None
    logger.info("🔄 Assistant reset")
