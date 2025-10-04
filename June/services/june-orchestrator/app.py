# June/services/june-orchestrator/app.py
# Enhanced orchestrator with Service-to-Service Authentication

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

app = FastAPI(title="June Orchestrator", version="3.3.0", description="June AI Platform Orchestrator with Service-to-Service Auth")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Storage for transcript notifications (in-memory for now)
transcript_storage = {}

# Service-to-Service Authentication Configuration
SERVICE_TO_SERVICE_TOKENS = {
    "june-stt": os.getenv("STT_SERVICE_TOKEN", "stt-service-secret-token-2025"),
    "june-tts": os.getenv("TTS_SERVICE_TOKEN", "tts-service-secret-token-2025"),
    "internal": os.getenv("INTERNAL_SERVICE_TOKEN", "internal-service-secret-2025")
}

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

# Authentication dependencies
async def verify_user_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Verify user authentication token from frontend"""
    if not SHARED_AUTH_AVAILABLE:
        logger.warning("⚠️ Authentication disabled - shared auth not available")
        return {"sub": "anonymous", "authenticated": False, "reason": "auth_disabled"}
    
    try:
        token = credentials.credentials
        logger.debug(f"🔍 Verifying user token: {token[:20]}...")
        
        auth_service = get_auth_service()
        token_data = await auth_service.verify_bearer(token)
        
        user_id = token_data.get('sub', 'unknown')
        logger.info(f"✅ User authenticated: {user_id}")
        return token_data
        
    except AuthError as e:
        logger.error(f"❌ User authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")
    except Exception as e:
        logger.error(f"❌ User authentication error: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")

async def verify_service_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Verify service-to-service authentication token"""
    try:
        token = credentials.credentials
        logger.debug(f"🔍 Verifying service token: {token[:20]}...")
        
        # Check against known service tokens
        for service_name, service_token in SERVICE_TO_SERVICE_TOKENS.items():
            if token == service_token:
                logger.info(f"✅ Service authenticated: {service_name}")
                return {
                    "service": service_name,
                    "authenticated": True,
                    "type": "service_to_service"
                }
        
        # If not a service token, could be a user token - let fallback handle it
        logger.warning(f"❌ Unknown service token: {token[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid service token")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Service authentication error: {e}")
        raise HTTPException(status_code=401, detail="Service authentication failed")

@app.get("/")
async def root():
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    
    return {
        "service": "June Orchestrator",
        "version": "3.3.0",
        "status": "healthy",
        "authentication": {
            "user_auth_enabled": SHARED_AUTH_AVAILABLE,
            "service_auth_enabled": True,
            "supported_services": list(SERVICE_TO_SERVICE_TOKENS.keys())
        },
        "features": {
            "ai_chat": gemini_service.is_available, 
            "text_to_speech": tts_status.get("available", False),
            "transcript_notifications": True,
            "service_to_service_auth": True  # NEW
        },
        "ai_provider": "gemini" if gemini_service.is_available else "fallback",
        "tts_service_url": os.getenv("TTS_SERVICE_URL", "not_configured"),
        "endpoints": {
            "health": "/healthz", 
            "chat": "/v1/chat", 
            "transcripts": "/v1/transcripts",
            "service_transcripts": "/v1/service/transcripts",  # NEW
            "tts_status": "/v1/tts/status",
            "auth_test": "/v1/auth/test"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator", 
        "version": "3.3.0", 
        "timestamp": time.time(),
        "ai_available": gemini_service.is_available,
        "user_auth_available": SHARED_AUTH_AVAILABLE,
        "service_auth_available": True,
        "transcripts_stored": len(transcript_storage)
    }

# NEW: Service-to-Service transcript notification endpoint
@app.post("/v1/service/transcripts", response_model=TranscriptResponse)
async def receive_service_transcript_notification(
    notification: TranscriptNotification,
    service_auth: Dict[str, Any] = Depends(verify_service_token)
):
    """
    Service-to-Service transcript notification endpoint
    
    Used by STT service to notify orchestrator without user authentication.
    Requires valid service token in Authorization header.
    """
    try:
        service_name = service_auth.get("service", "unknown")
        
        logger.info(f"📝 Received service transcript notification from {service_name}")
        logger.info(f"📋 Transcript ID: {notification.transcript_id}")
        logger.info(f"👤 User: {notification.user_id}")
        logger.info(f"📄 Text: {notification.text[:100]}..." if len(notification.text) > 100 else f"📄 Text: {notification.text}")
        logger.info(f"📊 Metadata: {notification.metadata}")
        
        # Store transcript in memory with service info
        transcript_data = {
            "transcript_id": notification.transcript_id,
            "user_id": notification.user_id,
            "text": notification.text,
            "timestamp": notification.timestamp,
            "metadata": notification.metadata,
            "received_at": datetime.utcnow().isoformat(),
            "source_service": service_name,
            "auth_type": "service_to_service"
        }
        
        transcript_storage[notification.transcript_id] = transcript_data
        
        # Enhanced processing based on content
        text_lower = notification.text.lower()
        if any(keyword in text_lower for keyword in ["urgent", "help", "emergency", "issue"]):
            logger.info(f"🚨 Urgent transcript detected: {notification.transcript_id}")
            transcript_data["priority"] = "high"
        
        if any(keyword in text_lower for keyword in ["thank you", "thanks", "appreciate"]):
            logger.info(f"😊 Positive sentiment detected: {notification.transcript_id}")
            transcript_data["sentiment"] = "positive"
        
        # Mark as processed
        transcript_data["processed"] = True
        
        response = TranscriptResponse(
            status="received",
            transcript_id=notification.transcript_id,
            timestamp=datetime.utcnow().isoformat(),
            message=f"Service transcript notification received from {service_name}",
            user_id=notification.user_id
        )
        
        logger.info(f"✅ Processed service transcript notification: {notification.transcript_id} from {service_name}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing service transcript notification: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process service transcript notification: {str(e)}"
        )

# Original user transcript notification endpoint (unchanged)
@app.post("/v1/transcripts", response_model=TranscriptResponse)
async def receive_transcript_notification(
    notification: TranscriptNotification,
    user_auth: Dict[str, Any] = Depends(verify_user_token)
):
    """
    User transcript notification endpoint (requires user authentication)
    """
    try:
        authenticated_user_id = user_auth.get("sub", "unknown")
        
        if notification.user_id != authenticated_user_id:
            logger.warning(f"❌ User mismatch: authenticated={authenticated_user_id}, notification={notification.user_id}")
            raise HTTPException(status_code=403, detail="Access denied - user mismatch")
        
        logger.info(f"📝 Received user transcript notification: {notification.transcript_id}")
        logger.info(f"👤 User: {authenticated_user_id}")
        logger.info(f"📄 Text: {notification.text[:100]}..." if len(notification.text) > 100 else f"📄 Text: {notification.text}")
        
        transcript_data = {
            "transcript_id": notification.transcript_id,
            "user_id": notification.user_id,
            "text": notification.text,
            "timestamp": notification.timestamp,
            "metadata": notification.metadata,
            "received_at": datetime.utcnow().isoformat(),
            "auth_type": "user_authenticated"
        }
        
        transcript_storage[notification.transcript_id] = transcript_data
        
        response = TranscriptResponse(
            status="received",
            transcript_id=notification.transcript_id,
            timestamp=datetime.utcnow().isoformat(),
            message="User transcript notification received successfully",
            user_id=authenticated_user_id
        )
        
        logger.info(f"✅ Processed user transcript notification: {notification.transcript_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing user transcript notification: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process user transcript notification: {str(e)}"
        )

# Get transcript history endpoint
@app.get("/v1/transcripts")
async def get_transcripts(
    user_auth: Dict[str, Any] = Depends(verify_user_token),
    limit: int = 50
):
    """Get transcript history for the authenticated user"""
    try:
        authenticated_user_id = user_auth.get("sub", "unknown")
        
        user_transcripts = [
            transcript for transcript in transcript_storage.values()
            if transcript["user_id"] == authenticated_user_id
        ]
        
        user_transcripts.sort(key=lambda x: x["timestamp"], reverse=True)
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
    user_auth: Dict[str, Any] = Depends(verify_user_token)
):
    start_time = time.time()
    
    try:
        user_id = user_auth.get("sub", "unknown")
        logger.info(f"🔐 Processing chat request for user: {user_id}")
        
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

@app.get("/v1/tts/status")
async def tts_status():
    tts_client = get_tts_client()
    return await tts_client.get_status()

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

# NEW: Service authentication test endpoint
@app.get("/v1/service/auth/test")
async def test_service_auth(service_auth: Dict[str, Any] = Depends(verify_service_token)):
    """Test endpoint to verify service authentication"""
    return {
        "authenticated": True,
        "service": service_auth.get("service"),
        "auth_type": service_auth.get("type"),
        "timestamp": time.time(),
        "message": f"Service {service_auth.get('service')} authenticated successfully"
    }

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v3.3.0 with Service-to-Service Auth")
    logger.info(f"TTS Service URL: {os.getenv('TTS_SERVICE_URL', 'not_configured')}")
    logger.info(f"User Authentication: {'ENABLED' if SHARED_AUTH_AVAILABLE else 'DISABLED'}")
    logger.info(f"Service Authentication: ENABLED")
    logger.info(f"Supported Services: {list(SERVICE_TO_SERVICE_TOKENS.keys())}")
    
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
