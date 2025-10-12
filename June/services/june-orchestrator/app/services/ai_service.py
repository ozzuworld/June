"""AI service - Gemini integration"""
import logging
import time
from typing import Optional

from ..config import config

logger = logging.getLogger(__name__)


async def generate_response(
    text: str,
    user_id: str,
    session_id: str,
    conversation_history: list = None
) -> tuple[str, int]:
    """
    Generate AI response using Gemini
    Returns: (response_text, processing_time_ms)
    """
    start_time = time.time()
    
    try:
        if not config.services.gemini_api_key:
            logger.warning("Gemini API key not configured")
            return fallback_response(text), int((time.time() - start_time) * 1000)
        
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=config.services.gemini_api_key)
        
        # Build context from history
        context = ""
        if conversation_history:
            recent = conversation_history[-5:]  # Last 5 messages
            context = "\n".join([
                f"{msg['role']}: {msg['content']}" 
                for msg in recent
            ])
        
        prompt = f"""You are JUNE, a helpful AI assistant.

{f"Previous conversation:{context}" if context else ""}

User says: "{text}"

Respond naturally and helpfully. Keep responses concise but informative."""
        
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=500
            )
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        if response and response.text:
            ai_text = response.text.strip()
            logger.info(f"✅ AI response generated in {processing_time}ms")
            return ai_text, processing_time
        
        return fallback_response(text), processing_time
        
    except Exception as e:
        processing_time = int((time.time() - start_time) * 1000)
        logger.error(f"AI service error: {e}")
        return fallback_response(text), processing_time


def fallback_response(text: str) -> str:
    """Fallback when AI unavailable"""
    text_lower = text.lower()
    
    if any(g in text_lower for g in ['hello', 'hi', 'hey']):
        return "Hello! I'm JUNE, your AI assistant. How can I help you today?"
    
    return f"I heard you say: '{text[:100]}...' I'm here to help!"