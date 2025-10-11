"""
AI Service - Gemini Integration
"""
import logging
from typing import Optional

from ..config import config

logger = logging.getLogger(__name__)


async def generate_response(
    text: str,
    user_id: str,
    temperature: float = 0.7,
    session_id: Optional[str] = None
) -> str:
    """
    Generate AI response using Gemini
    
    Args:
        text: User input text
        user_id: User identifier
        temperature: Response randomness (0.0-1.0)
        session_id: Optional session for context
        
    Returns:
        AI generated text response
    """
    try:
        logger.info(f"Generating AI response for {user_id}: {text[:50]}...")
        
        if not config.services.gemini_api_key:
            logger.warning("Gemini API key not configured")
            return fallback_response(text)
        
        try:
            from google import genai
            from google.genai import types
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            prompt = f"""You are JUNE, a helpful and friendly AI assistant created by OZZU.

User says: "{text}"

Please respond in a conversational, helpful manner. Keep responses concise but informative.
If the user is greeting you, introduce yourself as JUNE from OZZU."""
            
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=500,
                    candidate_count=1
                )
            )
            
            if response and response.text:
                ai_text = response.text.strip()
                logger.info(f"✅ AI response: {ai_text[:100]}...")
                return ai_text
                
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return fallback_response(text)
        
        return fallback_response(text)
        
    except Exception as e:
        logger.error(f"AI service error: {e}")
        return fallback_response(text)


def fallback_response(text: str) -> str:
    """Fallback response when AI is unavailable"""
    text_lower = text.lower()
    
    if any(greeting in text_lower for greeting in ['hello', 'hi', 'hey']):
        return "Hello! I'm JUNE, your AI assistant from OZZU. How can I help you today?"
    
    return f"I received your message: '{text[:100]}...' I'm here to help!"