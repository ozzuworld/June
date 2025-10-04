# June/services/june-orchestrator/app.py
# Enhanced orchestrator with FIXED AUTHENTICATION and Transcript Notifications

import os
import time
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# FIXED: Import the correct auth service for USER authentication
try:
    from shared.auth import get_auth_service, AuthError
    SHARED_AUTH_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Shared auth module loaded")
except ImportError:
    # Fallback if shared auth not available
    SHARED_AUTH_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Shared auth module not available, authentication will be disabled")

security = HTTPBearer()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Gemini imports
USING_NEW_SDK = False
try:
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
    logger.info("✅ Using new Google GenAI SDK")
except ImportError:
    try:
        import google.generativeai as genai
        USING_NEW_SDK = False
        logger.info("✅ Using legacy google-generativeai library")
    except ImportError:
        logger.error("❌ No Gemini library found")
        genai = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from tts_client import get_tts_client

app = FastAPI(title="June Orchestrator", version="3.2.0", description="June AI Platform Orchestrator with transcript notifications")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Storage for transcript notifications (in-memory for now)
transcript_storage = {}

class AudioConfig(BaseModel):
    voice: Optional[str] = Field(default="default")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    language: Optional[str] = Field(default="EN")
    reference_audio_b64: Optional[str] = Field(default=None)

class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1000, ge=1, le=4000)
    include_audio: Optional[bool] = Field(default=False)
    audio_config: Optional[AudioConfig] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default={})

class AudioData(BaseModel):
    data: str = Field(...)
    content_type: str = Field(default="audio/wav")
    size_bytes: int = Field(...)
    voice: str = Field(...)
    speed: float = Field(...)
    language: str = Field(...)

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"
    audio: Optional[AudioData] = Field(default=None)

# NEW: Transcript notification models
class TranscriptNotification(BaseModel):
    transcript_id: str
    user_id: str
    text: str
    timestamp: str  # ISO format datetime string
    metadata: Dict[str, Any] = {}

class TranscriptResponse(BaseModel):
    status: str
    transcript_id: str
    timestamp: str
    message: str
    user_id: str

class GeminiService:
    def __init__(self):
        self.model = None
        self.client = None
        self.api_key = None
        self.is_available = False
        self.initialize()
    
    def initialize(self):
        try:
            self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
            
            if not self.api_key or len(self.api_key) < 30:
                logger.warning("❌ GEMINI_API_KEY not set or invalid")
                return False
            
            if not genai:
                logger.warning("❌ No Gemini library available")
                return False
            
            logger.info(f"🔧 Initializing Gemini with API key: {self.api_key[:10]}...")
            
            if USING_NEW_SDK:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ New GenAI SDK configured")
                
                try:
                    # Test with a simple message to verify setup
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash', 
                        contents='Hello, are you working?'
                    )
                    if response and response.text:
                        logger.info(f"✅ Gemini test successful: {response.text[:50]}...")
                        self.is_available = True
                        return True
                    else:
                        logger.warning("❌ Gemini test returned empty response")
                        return False
                except Exception as e:
                    logger.warning(f"❌ New SDK test failed: {e}")
                    try:
                        response = self.client.models.generate_content(
                            model='gemini-2.0-flash-exp', 
                            contents='Hello, are you working?'
                        )
                        if response and response.text:
                            logger.info(f"✅ Gemini 2.0 test successful: {response.text[:50]}...")
                            self.is_available = True
                            return True
                    except Exception as e2:
                        logger.warning(f"❌ Gemini 2.0 also failed: {e2}")
                        return False
            else:
                genai.configure(api_key=self.api_key)
                try:
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    test_response = self.model.generate_content("Hello, are you working?")
                    if test_response and test_response.text:
                        logger.info(f"✅ Legacy SDK test successful: {test_response.text[:50]}...")
                        self.is_available = True
                        return True
                    else:
                        logger.warning("❌ Legacy SDK test returned empty response")
                        return False
                except Exception as e:
                    logger.error(f"❌ Legacy SDK test failed: {e}")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            return False
    
    async def generate_response(self, text: str, language: str = "en", temperature: float = 0.7) -> tuple[str, str]:
        if not self.is_available:
            logger.warning("❌ Gemini not available, using fallback")
            return self._get_fallback_response(text, language), "fallback"
        
        try:
            system_prompts = {
                "en": "You are JUNE, a helpful AI assistant. Provide clear, accurate, and helpful responses. Be conversational and engaging.",
                "es": "Eres JUNE, un asistente de IA útil. Proporciona respuestas claras, precisas y útiles en español. Sé conversacional y atractivo.",
                "fr": "Vous êtes JUNE, un assistant IA utile. Fournissez des réponses claires, précises et utiles en français. Soyez conversationnel et engageant."
            }
            
            system_prompt = system_prompts.get(language, system_prompts["en"])
            full_prompt = f"{system_prompt}\n\nUser: {text}\n\nAssistant:"
            
            logger.info(f"🤖 Generating AI response for: {text[:50]}...")
            
            if USING_NEW_SDK and self.client:
                try:
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            temperature=temperature, 
                            max_output_tokens=1000
                        )
                    )
                    
                    if response and response.text:
                        ai_text = response.text.strip()
                        logger.info(f"✅ Gemini 1.5 response: {ai_text[:100]}...")
                        return ai_text, "gemini-new-sdk"
                    else:
                        logger.warning("❌ Empty response from Gemini 1.5")
                        
                except Exception as e:
                    logger.warning(f"❌ Gemini 1.5 failed: {e}, trying 2.0...")
                    try:
                        response = self.client.models.generate_content(
                            model='gemini-2.0-flash-exp',
                            contents=full_prompt,
                            config=types.GenerateContentConfig(
                                temperature=temperature, 
                                max_output_tokens=1000
                            )
                        )
                        
                        if response and response.text:
                            ai_text = response.text.strip()
                            logger.info(f"✅ Gemini 2.0 response: {ai_text[:100]}...")
                            return ai_text, "gemini-2.0-exp"
                    except Exception as e2:
                        logger.error(f"❌ Both Gemini models failed: {e2}")
            else:
                if self.model:
                    generation_config = genai.types.GenerationConfig(
                        temperature=temperature, 
                        max_output_tokens=1000
                    )
                    response = self.model.generate_content(
                        full_prompt, 
                        generation_config=generation_config
                    )
                    
                    if response and response.text:
                        ai_text = response.text.strip()
                        logger.info(f"✅ Legacy Gemini response: {ai_text[:100]}...")
                        return ai_text, "gemini-legacy"
            
            # If we get here, all attempts failed
            logger.error("❌ All Gemini attempts failed, using fallback")
            return self._get_fallback_response(text, language), "fallback"
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return self._get_fallback_response(text, language), "fallback"
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        """IMPROVED fallback responses that are more helpful"""
        
        # Check for common questions first
        text_lower = text.lower()
        
        # Math questions
        if any(word in text_lower for word in ["what is", "calculate", "math", "plus", "minus", "times", "divided"]):
            if "2+2" in text_lower or "2 + 2" in text_lower:
                return "2 + 2 = 4. This is basic arithmetic."
            elif "pi" in text_lower:
                return "Pi (π) is approximately 3.14159. It's the ratio of a circle's circumference to its diameter."
            return "I can help with math questions, but I need a clear mathematical expression to calculate."
        
        # Weather questions  
        if any(word in text_lower for word in ["weather", "temperature", "rain", "sunny", "cloudy"]):
            return "I don't have access to real-time weather data. Please check a weather app or website for current conditions in your area."
        
        # Greetings
        if any(word in text_lower for word in ["hello", "hi", "hey", "good morning", "good afternoon"]):
            greetings = {
                "en": "Hello! I'm JUNE, your AI assistant. How can I help you today?",
                "es": "¡Hola! Soy JUNE, tu asistente de IA. ¿Cómo puedo ayudarte hoy?",
                "fr": "Bonjour! Je suis JUNE, votre assistant IA. Comment puis-je vous aider aujourd'hui?"
            }
            return greetings.get(language, greetings["en"])
        
        # Default helpful response
        defaults = {
            "en": f"I understand you're asking about '{text}'. While I'm currently in basic mode, I'm here to help with general questions, math, and conversation. What specific information do you need?",
            "es": f"Entiendo que preguntas sobre '{text}'. Aunque estoy en modo básico, estoy aquí para ayudarte con preguntas generales, matemáticas y conversación. ¿Qué información específica necesitas?",
            "fr": f"Je comprends que vous demandez à propos de '{text}'. Bien que je sois en mode de base, je suis là pour vous aider avec des questions générales, des mathématiques et la conversation. Quelles informations spécifiques avez-vous besoin?"
        }
        
        return defaults.get(language, defaults["en"])

gemini_service = GeminiService()

# FIXED: Proper user authentication dependency
async def verify_user_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Verify user authentication token from frontend
    This is the CORRECT way to handle user authentication
    """
    if not SHARED_AUTH_AVAILABLE:
        logger.warning("⚠️ Authentication disabled - shared auth not available")
        return {"sub": "anonymous", "authenticated": False, "reason": "auth_disabled"}
    
    try:
        # Get the token from the Authorization header
        token = credentials.credentials
        logger.debug(f"🔍 Verifying token: {token[:20]}...")
        
        # Validate the user token using the shared auth service
        auth_service = get_auth_service()
        token_data = await auth_service.verify_bearer(token)
        
        user_id = token_data.get('sub', 'unknown')
        logger.info(f"✅ User authenticated: {user_id}")
        return token_data
        
    except AuthError as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")
    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")

@app.get("/")
async def root():
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    
    return {
        "service": "June Orchestrator",
        "version": "3.2.0",
        "status": "healthy",
        "authentication": {
            "enabled": SHARED_AUTH_AVAILABLE,
            "type": "user_token_validation"
        },
        "features": {
            "ai_chat": gemini_service.is_available, 
            "text_to_speech": tts_status.get("available", False),
            "transcript_notifications": True  # NEW
        },
        "ai_provider": "gemini" if gemini_service.is_available else "fallback",
        "tts_service_url": os.getenv("TTS_SERVICE_URL", "not_configured"),
        "endpoints": {
            "health": "/healthz", 
            "chat": "/v1/chat", 
            "transcripts": "/v1/transcripts",  # NEW
            "tts_status": "/v1/tts/status",
            "auth_test": "/v1/auth/test",
            "auth_debug": "/v1/auth/debug"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator", 
        "version": "3.2.0", 
        "timestamp": time.time(),
        "ai_available": gemini_service.is_available,
        "auth_available": SHARED_AUTH_AVAILABLE,
        "transcripts_stored": len(transcript_storage)
    }

# NEW: Transcript notification endpoint
@app.post("/v1/transcripts", response_model=TranscriptResponse)
async def receive_transcript_notification(
    notification: TranscriptNotification,
    user_auth: Dict[str, Any] = Depends(verify_user_token)
):
    """
    Receive transcript notification from STT service
    
    This endpoint allows the orchestrator to:
    - Track all transcriptions
    - Trigger additional AI workflows
    - Store transcripts for analytics
    - Maintain conversation history
    """
    try:
        authenticated_user_id = user_auth.get("sub", "unknown")
        
        # Verify the transcript belongs to the authenticated user
        if notification.user_id != authenticated_user_id:
            logger.warning(f"❌ User mismatch: authenticated={authenticated_user_id}, notification={notification.user_id}")
            raise HTTPException(status_code=403, detail="Access denied - user mismatch")
        
        logger.info(f"📝 Received transcript notification: {notification.transcript_id}")
        logger.info(f"👤 User: {authenticated_user_id}")
        logger.info(f"📄 Text: {notification.text[:100]}..." if len(notification.text) > 100 else f"📄 Text: {notification.text}")
        logger.info(f"📊 Metadata: {notification.metadata}")
        
        # Store transcript in memory (you could extend this to database storage)
        transcript_data = {
            "transcript_id": notification.transcript_id,
            "user_id": notification.user_id,
            "text": notification.text,
            "timestamp": notification.timestamp,
            "metadata": notification.metadata,
            "received_at": datetime.utcnow().isoformat(),
            "processed": False
        }
        
        transcript_storage[notification.transcript_id] = transcript_data
        
        # Here you can add additional processing logic:
        # 1. Trigger automated AI responses for certain keywords
        # 2. Store in persistent database
        # 3. Send to analytics service
        # 4. Queue for background processing
        # 5. Update conversation context
        
        # Example: Trigger automated processing for certain keywords
        text_lower = notification.text.lower()
        if any(keyword in text_lower for keyword in ["urgent", "help", "emergency", "issue"]):
            logger.info(f"🚨 Urgent transcript detected: {notification.transcript_id}")
            transcript_data["priority"] = "high"
            # You could trigger immediate processing here
        
        if any(keyword in text_lower for keyword in ["thank you", "thanks", "appreciate"]):
            logger.info(f"😊 Positive sentiment detected: {notification.transcript_id}")
            transcript_data["sentiment"] = "positive"
        
        # Mark as processed
        transcript_data["processed"] = True
        
        response = TranscriptResponse(
            status="received",
            transcript_id=notification.transcript_id,
            timestamp=datetime.utcnow().isoformat(),
            message="Transcript notification received and processed successfully",
            user_id=authenticated_user_id
        )
        
        logger.info(f"✅ Processed transcript notification: {notification.transcript_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing transcript notification: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process transcript notification: {str(e)}"
        )

# NEW: Get transcript history endpoint
@app.get("/v1/transcripts")
async def get_transcripts(
    user_auth: Dict[str, Any] = Depends(verify_user_token),
    limit: int = 50
):
    """Get transcript history for the authenticated user"""
    try:
        authenticated_user_id = user_auth.get("sub", "unknown")
        
        # Filter transcripts for this user
        user_transcripts = [
            transcript for transcript in transcript_storage.values()
            if transcript["user_id"] == authenticated_user_id
        ]
        
        # Sort by timestamp (newest first)
        user_transcripts.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Apply limit
        limited_transcripts = user_transcripts[:limit]
        
        return {
            "transcripts": limited_transcripts,
            "total": len(user_transcripts),
            "showing": len(limited_transcripts),
            "user_id": authenticated_user_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error retrieving transcripts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve transcripts: {str(e)}")

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user_auth: Dict[str, Any] = Depends(verify_user_token)  # FIXED: Use proper user auth
):
    start_time = time.time()
    
    try:
        # Log successful authentication
        user_id = user_auth.get("sub", "unknown")
        logger.info(f"🔐 Processing chat request for user: {user_id}")
        
        # Generate AI response
        ai_response, provider = await gemini_service.generate_response(
            request.text.strip(), 
            request.language, 
            request.temperature
        )
        
        response_time = int((time.time() - start_time) * 1000)
        
        chat_response = ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=provider
        )
        
        # Add TTS audio if requested
        if request.include_audio:
            try:
                logger.info("🔊 Generating TTS audio...")
                tts_client = get_tts_client()
                audio_config = request.audio_config or AudioConfig()
                
                audio_result = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice=audio_config.voice,
                    speed=audio_config.speed,
                    language=audio_config.language,
                    reference_audio_b64=audio_config.reference_audio_b64
                )
                
                audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                
                chat_response.audio = AudioData(
                    data=audio_b64,
                    content_type=audio_result["content_type"],
                    size_bytes=audio_result["size_bytes"],
                    voice=audio_result["voice"],
                    speed=audio_result["speed"],
                    language=audio_result["language"]
                )
                
                logger.info(f"✅ TTS audio generated: {audio_result['size_bytes']} bytes")
                
            except Exception as e:
                logger.error(f"❌ TTS generation failed: {e}")
                # Continue without audio - don't fail the whole request
        
        logger.info(f"✅ Chat response completed: {provider} ({response_time}ms)")
        return chat_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"I apologize, but I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

# Legacy endpoint for backward compatibility
@app.post("/v1/conversation", response_model=ChatResponse)
async def conversation(
    request: ChatRequest,
    user_auth: Dict[str, Any] = Depends(verify_user_token)  # FIXED: Add auth here too
):
    """Legacy endpoint - redirects to /v1/chat with authentication"""
    return await chat(request, user_auth)

@app.get("/v1/tts/status")
async def tts_status():
    tts_client = get_tts_client()
    return await tts_client.get_status()

# ADDED: Authentication test endpoints
@app.get("/v1/auth/test")
async def test_auth(user_auth: Dict[str, Any] = Depends(verify_user_token)):
    """Test endpoint to verify user authentication"""
    return {
        "authenticated": True,
        "user_id": user_auth.get("sub"),
        "client_id": user_auth.get("azp", user_auth.get("client_id")),
        "scopes": user_auth.get("scope", "").split(),
        "expires_at": user_auth.get("exp"),
        "issued_at": user_auth.get("iat"),
        "timestamp": time.time()
    }

@app.get("/v1/auth/debug")
async def debug_auth():
    """Debug endpoint to test Keycloak connectivity"""
    if not SHARED_AUTH_AVAILABLE:
        return {
            "error": "Shared auth module not available",
            "shared_auth_available": False
        }
    
    try:
        from shared.auth import test_keycloak_connection
        result = await test_keycloak_connection()
        result["shared_auth_available"] = True
        return result
    except Exception as e:
        return {
            "error": str(e),
            "shared_auth_available": True,
            "connection_test_failed": True
        }

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v3.2.0 with transcript notifications")
    logger.info(f"TTS Service URL: {os.getenv('TTS_SERVICE_URL', 'not_configured')}")
    logger.info(f"Authentication: {'ENABLED' if SHARED_AUTH_AVAILABLE else 'DISABLED'}")
    
    if gemini_service.is_available:
        logger.info("✅ Gemini AI service ready")
    else:
        logger.warning("⚠️ Gemini AI service not ready - using fallback responses")
    
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    if tts_status.get("available", False):
        logger.info("✅ External TTS service ready")
    else:
        logger.warning("⚠️ External TTS service not reachable")

# OPTIONAL: Keep service auth endpoint for debugging
@app.get("/v1/service-auth/status")
async def service_auth_status():
    """Test service-to-service authentication (for debugging only)"""
    try:
        from service_auth import get_service_auth_client
        client = get_service_auth_client()
        auth_status = await client.test_authentication()
        
        return {
            "service_auth": auth_status,
            "timestamp": time.time(),
            "note": "This is for service-to-service auth, not user auth"
        }
    except Exception as e:
        return {
            "service_auth": {"error": str(e)},
            "timestamp": time.time()
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
