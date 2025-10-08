import logging
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Direct Gemini integration
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = bool(settings.gemini_api_key)
    if GEMINI_AVAILABLE:
        client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("✅ Gemini AI client initialized")
    else:
        client = None
        logger.warning("⚠️ No Gemini API key provided")
except ImportError:
    GEMINI_AVAILABLE = False
    client = None
    logger.warning("⚠️ Gemini SDK not available")

SYSTEM_PROMPT = """You are JUNE, a helpful AI assistant. You provide clear, concise, and friendly responses. 
Keep your responses conversational and engaging, but not overly long unless specifically asked for detail."""

async def generate_ai_response(text: str, user_id: str) -> str:
    """Generate AI response directly using Gemini"""
    
    if not GEMINI_AVAILABLE or not client:
        return get_fallback_response(text)
    
    try:
        logger.info(f"🤖 Generating AI response for user {user_id}: {text[:50]}...")
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{SYSTEM_PROMPT}\n\nUser: {text}",
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=1000,
                top_p=0.8,
                top_k=40
            )
        )
        
        if response and response.text:
            ai_text = response.text.strip()
            logger.info(f"✅ AI response generated: {ai_text[:100]}...")
            return ai_text
        
        logger.warning("⚠️ Empty response from Gemini")
        return get_fallback_response(text)
        
    except Exception as e:
        logger.error(f"❌ AI generation failed: {e}")
        return get_fallback_response(text)

def get_fallback_response(text: str) -> str:
    """Simple fallback when AI is unavailable"""
    text_lower = text.lower()
    
    # Basic pattern matching for common queries
    if any(word in text_lower for word in ["hello", "hi", "hey", "good morning", "good afternoon"]):
        return "Hello! I'm JUNE, your AI assistant. How can I help you today?"
    
    if any(word in text_lower for word in ["thank", "thanks", "appreciate"]):
        return "You're welcome! Is there anything else I can help you with?"
    
    if any(word in text_lower for word in ["how are you", "how's it going"]):
        return "I'm doing well, thank you for asking! I'm here and ready to help with whatever you need."
    
    if any(word in text_lower for word in ["what can you do", "what are your capabilities", "help me"]):
        return "I can help you with questions, have conversations, provide information, and assist with various tasks. What would you like to know or discuss?"
    
    if any(word in text_lower for word in ["goodbye", "bye", "see you", "talk later"]):
        return "Goodbye! Feel free to come back anytime if you need help. Have a great day!"
    
    # Default response
    return f"I received your message: '{text[:100]}...' I'm currently running in basic mode, but I'm still here to help! Could you tell me more about what you need?"

def is_ai_available() -> bool:
    """Check if AI service is available"""
    return GEMINI_AVAILABLE and client is not None