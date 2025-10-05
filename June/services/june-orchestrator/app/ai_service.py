"""
Simplified Gemini AI service
"""
import logging
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime

from app.config import get_gemini_api_key

logger = logging.getLogger(__name__)

# Try to import Gemini
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("⚠️ Gemini SDK not available")


@lru_cache(maxsize=1)
def get_gemini_client():
    """Get Gemini client (cached)"""
    if not GEMINI_AVAILABLE:
        return None
    
    api_key = get_gemini_api_key()
    if not api_key:
        logger.warning("❌ No valid Gemini API key")
        return None
    
    try:
        client = genai.Client(api_key=api_key)
        logger.info("✅ Gemini client initialized")
        return client
    except Exception as e:
        logger.error(f"❌ Failed to initialize Gemini: {e}")
        return None


def get_system_prompt(language: str) -> str:
    """Get system prompt for language"""
    prompts = {
        "en": "You are JUNE, a helpful AI assistant.",
        "es": "Eres JUNE, un asistente de IA útil.",
    }
    return prompts.get(language, prompts["en"])


def build_conversation_context(
    history: List[Dict[str, Any]], 
    user_message: str, 
    language: str
) -> str:
    """Build context from conversation history"""
    parts = [get_system_prompt(language)]
    
    # Add last 5 messages for context
    for msg in history[-5:]:
        role = msg.get("role", "user")
        text = msg.get("text", "")
        parts.append(f"{role}: {text}")
    
    parts.append(f"user: {user_message}")
    return "\n\n".join(parts)


async def generate_ai_response(
    text: str,
    user_id: str,
    conversation_history: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """
    Generate AI response using Gemini
    
    Args:
        text: User's message
        user_id: User identifier
        conversation_history: Previous messages
        language: Language code
        
    Returns:
        AI response text
    """
    client = get_gemini_client()
    
    if not client:
        return get_fallback_response(text)
    
    try:
        # Build context with history
        context = build_conversation_context(conversation_history, text, language)
        
        logger.debug(f"🤖 Generating response for user {user_id}")
        
        # Generate response
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=context,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=1000
            )
        )
        
        if response and response.text:
            ai_text = response.text.strip()
            logger.info(f"✅ Generated response: {ai_text[:50]}...")
            return ai_text
        
        logger.warning("⚠️ Empty response from Gemini")
        return get_fallback_response(text)
        
    except Exception as e:
        logger.error(f"❌ AI generation failed: {e}")
        return get_fallback_response(text)


def get_fallback_response(text: str) -> str:
    """Simple fallback when AI is unavailable"""
    text_lower = text.lower()
    
    if any(word in text_lower for word in ["hello", "hi", "hey"]):
        return "Hello! I'm JUNE. How can I help you today?"
    
    if any(word in text_lower for word in ["thank", "thanks"]):
        return "You're welcome! Anything else I can help with?"
    
    return f"I received your message: '{text}'. I'm currently in basic mode."


def is_ai_available() -> bool:
    """Check if AI service is available"""
    return get_gemini_client() is not None