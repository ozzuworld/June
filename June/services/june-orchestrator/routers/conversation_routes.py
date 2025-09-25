# June/services/june-orchestrator/routers/conversation_routes.py - FIXED VERSION
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import time
import uuid
import os

from db.session import get_db
from schemas.conversation import ConversationInput, ConversationOutput, MessageArtifact
from shared import require_user_auth, extract_user_id
from clients.http import get_http_client
from clients.tts_client import tts_generate

# Import Google Gemini AI
try:
    import google.generativeai as genai
    
    # Configure Gemini API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        AI_AVAILABLE = True
        logging.info("✅ Gemini AI initialized successfully")
    else:
        AI_AVAILABLE = False
        model = None
        logging.warning("⚠️ GEMINI_API_KEY not found - using fallback responses")
except ImportError as e:
    AI_AVAILABLE = False
    model = None
    logging.warning(f"⚠️ Gemini AI not available: {e}")

router = APIRouter(prefix="/v1", tags=["conversation"])
logger = logging.getLogger(__name__)

# ✅ ADD DEBUG ROUTE for testing
@router.get("/debug")
async def debug_routes():
    """Debug endpoint to verify routing is working"""
    return {
        "service": "june-orchestrator",
        "available_routes": [
            "/v1/conversation (POST) - Main chat endpoint",
            "/v1/debug (GET) - This debug endpoint", 
            "/healthz (GET) - Health check"
        ],
        "ai_status": {
            "gemini_available": AI_AVAILABLE,
            "api_key_configured": bool(GEMINI_API_KEY)
        },
        "current_time": time.time(),
        "status": "OK"
    }

async def generate_ai_response(user_text: str, user_id: str) -> str:
    """Generate AI response using Gemini or intelligent fallbacks"""
    try:
        if AI_AVAILABLE and model:
            logger.info(f"🤖 Generating AI response for: {user_text[:50]}...")
            
            # Create a context-aware prompt
            prompt = f"""You are OZZU, a helpful AI assistant. Respond naturally and helpfully to the user's question. Keep responses concise but informative.

User question: {user_text}

Provide a helpful, accurate response."""

            response = model.generate_content(prompt)
            ai_text = response.text.strip()
            
            logger.info(f"✅ AI response generated: {ai_text[:100]}...")
            return ai_text
            
        else:
            # Intelligent fallback responses for common questions
            user_lower = user_text.lower()
            
            # Math and science
            if "pi" in user_lower and ("what" in user_lower or "how much" in user_lower or "value" in user_lower):
                return "Pi (π) is approximately 3.14159265359. It's the ratio of a circle's circumference to its diameter, and it's an irrational number that goes on infinitely without repeating."
            elif "fibonacci" in user_lower:
                return "The Fibonacci sequence starts with 0, 1, and each subsequent number is the sum of the previous two: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144..."
            elif "golden ratio" in user_lower:
                return "The golden ratio (φ) is approximately 1.618033988749. It appears frequently in nature, art, and architecture."
                
            # Greetings
            elif any(word in user_lower for word in ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]):
                return "Hello! I'm OZZU, your AI assistant. I'm here to help answer questions, solve problems, and have conversations. What can I help you with today?"
                
            # Weather (we don't have real weather data)
            elif "weather" in user_lower:
                return "I don't have access to current weather data, but I'd suggest checking a weather app or website for your location. Is there anything else I can help you with?"
                
            # Time (we don't have real-time data)
            elif "time" in user_lower and ("what" in user_lower or "current" in user_lower):
                return "I don't have access to real-time data, but I can help with time zones, calculations, or other time-related questions. What specifically would you like to know?"
                
            # Calculations
            elif any(word in user_lower for word in ["calculate", "compute", "solve", "+", "-", "*", "/"]):
                return "I can help with calculations! Could you provide the specific math problem or equation you'd like me to solve?"
                
            # General knowledge
            elif "capital" in user_lower:
                return "I can help with geography and capitals! Which country or state are you asking about?"
            elif "how are you" in user_lower:
                return "I'm doing well, thank you for asking! I'm here and ready to help. How can I assist you today?"
            elif "what can you do" in user_lower:
                return "I can help with a variety of tasks including answering questions, explaining concepts, helping with math problems, providing information on various topics, and having conversations. What would you like help with?"
                
            # Default intelligent response
            else:
                # Try to be helpful based on question words
                if any(word in user_lower for word in ["what", "how", "why", "when", "where", "who"]):
                    return f"That's an interesting question about '{user_text}'. While I don't have specific information about this topic right now, I'd be happy to help you think through it or assist with related questions. Could you provide more context or ask something more specific?"
                else:
                    return f"I understand you mentioned '{user_text}'. I'm here to help! Could you tell me more about what specifically you'd like to know or discuss?"
                    
    except Exception as e:
        logger.error(f"❌ AI generation failed: {e}")
        return "I apologize, but I'm having trouble processing your request right now. Please try rephrasing your question or try again in a moment."

# ✅ FIXED: Add proper authentication dependency
@router.post("/conversation", response_model=ConversationOutput)
async def process_conversation(
    payload: ConversationInput,
    current_user: dict = Depends(require_user_auth),  # ✅ ADD: Authentication required
    db: Annotated[AsyncSession, Depends(get_db)],
    http = Depends(get_http_client),
) -> ConversationOutput:
    try:
        # ✅ ADD: Extract user info
        user_id = extract_user_id(current_user)
        logger.info(f"💬 Processing conversation for user {user_id}: {payload.text}")
        
        # Guard clauses
        if not (payload.text or payload.audio_b64):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide text or audio_b64."
            )

        is_text = bool(payload.text)
        if not is_text and payload.audio_b64:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="audio_b64 path not yet implemented in this patch"
            )

        # Generate AI response instead of echo
        start_time = time.time()
        response_text = await generate_ai_response(payload.text, user_id)
        processing_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ AI response generated in {processing_time}ms: {response_text[:100]}...")

        # Try to generate TTS if configured
        audio_url = None
        used_tools = ["ai"]
        warnings = []
        
        try:
            if response_text and len(response_text.strip()) > 0:
                tts_payload = {
                    "text": response_text,
                    "voice_id": payload.voice_id or "default",
                    "format": "wav",
                    "language": payload.language or "en",
                    "metadata": payload.metadata or {},
                }

                audio_bytes = await tts_generate(http, base_url=None, payload=tts_payload)
                if audio_bytes and len(audio_bytes) > 8:
                    used_tools.append("tts")
                    logger.info(f"🔊 TTS generated: {len(audio_bytes)} bytes")
                    # In production, save to object storage and return URL
                else:
                    logger.warning("⚠️ TTS generation returned empty audio")
                    warnings.append("TTS generation returned empty audio")
        except Exception as tts_error:
            logger.warning(f"⚠️ TTS generation failed: {tts_error}")
            warnings.append("TTS generation failed, but text response available")

        # Create response message
        message = MessageArtifact(
            id=f"msg_{uuid.uuid4().hex[:8]}",
            role="assistant", 
            text=response_text,
            audio_url=audio_url,
        )

        logger.info(f"✅ Conversation processed successfully for user {user_id}")

        return ConversationOutput(
            ok=True,
            conversation_id=f"conv_{user_id}_{int(time.time())}",
            message=message,
            used_tools=used_tools,
            warnings=warnings,
            errors=[],
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.exception(f"❌ Unexpected error in conversation processing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during conversation processing"
        )