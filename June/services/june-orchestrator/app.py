# June/services/june-orchestrator/app.py - UPDATED FOR KOKORO TTS
import os
import json
import uuid
import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends

# Import the shared auth module
from shared.auth_service import create_service_auth_client, require_service_auth, ServiceAuthClient

# Import Firebase auth (keeping existing functionality)
from authz import get_current_user

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="June Orchestrator", version="1.0.0")
voice_router = APIRouter()

logger = logging.getLogger("orchestrator.voice")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
FIREBASE_PROJECT_ID    = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_WEB_API_KEY   = os.getenv("FIREBASE_WEB_API_KEY", "")
INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_SHARED_SECRET", "")

# AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Initialize AI if available
ai_model = None
try:
    if GEMINI_API_KEY:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        
        genai.configure(api_key=GEMINI_API_KEY)
        
        # Create AI model with safety settings
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 1024,
        }
        
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }
        
        ai_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            safety_settings=safety_settings,
        )
        
        logger.info("✅ Gemini AI model initialized")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not set - using fallback responses")
except ImportError:
    logger.warning("⚠️ google-generativeai not installed - using fallback responses")
except Exception as e:
    logger.error(f"⚠️ Failed to initialize AI model: {e}")

# Service URLs (for calling other services)
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")  # Now points to Kokoro TTS

# Audio defaults
DEFAULT_LOCALE        = os.getenv("DEFAULT_LOCALE", "en-US")

# -----------------------------------------------------------------------------
# AI Helper Functions
# -----------------------------------------------------------------------------
async def generate_ai_response(user_input: str, user_context: dict = None) -> str:
    """Generate AI response using Gemini"""
    if not ai_model:
        return f"I received your message: '{user_input}'. However, AI is currently not configured. This is a placeholder response."
    
    try:
        # Create a conversational prompt
        system_prompt = """You are June, a helpful AI assistant. You are knowledgeable, friendly, and concise. 
        You can help with various tasks, answer questions, and have engaging conversations.
        
        Key traits:
        - Be helpful and informative
        - Keep responses conversational and engaging
        - If you don't know something, say so honestly
        - Be concise but thorough when needed
        """
        
        # Combine system prompt with user input
        full_prompt = f"{system_prompt}\n\nUser: {user_input}\n\nJune:"
        
        # Generate response
        response = ai_model.generate_content(full_prompt)
        
        if response.text:
            return response.text.strip()
        else:
            return "I'm having trouble generating a response right now. Could you try rephrasing your question?"
            
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        return f"I'm experiencing some technical difficulties. Here's what I can tell you about '{user_input}': I'd be happy to help, but I'm having trouble processing that right now."

# -----------------------------------------------------------------------------
# Service authentication setup
# -----------------------------------------------------------------------------
try:
    service_auth = create_service_auth_client("orchestrator")
    logger.info("✅ Service authentication initialized")
except Exception as e:
    logger.warning(f"⚠️ Service authentication not available: {e}")
    service_auth = None

# -----------------------------------------------------------------------------
# Enhanced Kokoro TTS client with authentication
# -----------------------------------------------------------------------------
class KokoroTTSClient:
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
        self.available_voices = {}
        
    async def initialize(self):
        """Initialize and get available voices"""
        try:
            response = await self.auth.make_authenticated_request(
                "GET",
                f"{self.base_url}/v1/voices",
                timeout=10.0
            )
            response.raise_for_status()
            voice_data = response.json()
            self.available_voices = voice_data.get("voices", {})
            logger.info(f"✅ Kokoro TTS initialized with voices: {list(self.available_voices.keys())}")
        except Exception as e:
            logger.error(f"⚠️ Failed to initialize Kokoro TTS: {e}")
            self.available_voices = {"af_bella": "American Female - Bella (fallback)"}
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "af_bella",
        speed: float = 1.0,
        audio_encoding: str = "MP3"
    ) -> bytes:
        """Call Kokoro TTS service with service authentication"""
        if not self.auth:
            raise Exception("Service authentication not configured")
        
        # Validate voice
        if voice not in self.available_voices and voice != "default":
            logger.warning(f"Voice '{voice}' not available, using af_bella")
            voice = "af_bella"
        
        url = f"{self.base_url}/v1/tts"
        
        params = {
            "text": text,
            "voice": voice,
            "speed": speed,
            "audio_encoding": audio_encoding
        }
        
        try:
            response = await self.auth.make_authenticated_request(
                "POST",
                url,
                params=params,
                timeout=30.0
            )
            
            response.raise_for_status()
            logger.info(f"✅ Kokoro TTS synthesis successful: {len(response.content)} bytes")
            return response.content
            
        except Exception as e:
            logger.error(f"❌ Kokoro TTS service call failed: {e}")
            raise

class AuthenticatedSTTClient:
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
    
    async def transcribe_audio(self, audio_data: bytes, language: str = "en-US") -> dict:
        """Call STT service with service authentication"""
        if not self.auth:
            raise Exception("Service authentication not configured")
        
        url = f"{self.base_url}/v1/transcribe"
        
        try:
            response = await self.auth.make_authenticated_request(
                "POST",
                url,
                files={"audio": audio_data},
                data={"language": language},
                timeout=30.0
            )
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"STT service call failed: {e}")
            raise

# Initialize service clients
stt_client = None
tts_client = None

if service_auth:
    if STT_SERVICE_URL:
        stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
        logger.info("✅ STT service client initialized")
    
    if TTS_SERVICE_URL:
        tts_client = KokoroTTSClient(TTS_SERVICE_URL, service_auth)
        logger.info("✅ Kokoro TTS service client initialized")

# -----------------------------------------------------------------------------
# Health and config endpoints
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-orchestrator", 
        "timestamp": time.time(),
        "status": "healthy",
        "ai_enabled": ai_model is not None,
        "tts_engine": "kokoro"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator", 
        "status": "running",
        "version": "1.0.0",
        "ai_enabled": ai_model is not None,
        "tts_engine": "kokoro"
    }

@app.get("/configz")
async def configz():
    """Configuration endpoint for debugging"""
    return {
        "FIREBASE_PROJECT_ID": FIREBASE_PROJECT_ID,
        "STT_SERVICE_URL": STT_SERVICE_URL,
        "TTS_SERVICE_URL": TTS_SERVICE_URL,
        "DEFAULT_LOCALE": DEFAULT_LOCALE,
        "service_auth_enabled": service_auth is not None,
        "stt_client_ready": stt_client is not None,
        "tts_client_ready": tts_client is not None,
        "ai_model_enabled": ai_model is not None,
        "gemini_api_key_present": bool(GEMINI_API_KEY),
        "tts_engine": "kokoro",
        "available_voices": getattr(tts_client, 'available_voices', {}) if tts_client else {}
    }

# -----------------------------------------------------------------------------
# Protected service endpoints with Kokoro TTS
# -----------------------------------------------------------------------------
@app.post("/v1/chat")
async def chat(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Chat endpoint protected by service authentication with AI integration"""
    user_text = (payload or {}).get("user_input", "")
    calling_service = service_auth_data.get("client_id", "unknown")
    
    logger.info(f"Chat request from service: {calling_service}")
    
    if not user_text.strip():
        return {
            "reply": "I didn't receive any message. What would you like to talk about?",
            "processed_by": "orchestrator",
            "caller": calling_service
        }
    
    # Generate AI response
    try:
        reply = await generate_ai_response(user_text, {"caller": calling_service})
        
        return {
            "reply": reply,
            "processed_by": "orchestrator", 
            "caller": calling_service,
            "ai_model": "gemini-1.5-flash" if ai_model else "fallback"
        }
        
    except Exception as e:
        logger.error(f"Chat processing error: {e}")
        return {
            "reply": f"I apologize, but I'm having trouble processing your message right now. Error: {str(e)}",
            "processed_by": "orchestrator",
            "caller": calling_service,
            "error": str(e)
        }

@app.post("/v1/process-audio")
async def process_audio(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Process audio through STT -> LLM -> Kokoro TTS pipeline"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"Audio processing request from service: {calling_service}")
    
    audio_data = payload.get("audio_data")  # base64 encoded audio
    if not audio_data:
        return {"error": "No audio data provided"}
    
    try:
        # Decode audio
        import base64
        audio_bytes = base64.b64decode(audio_data)
        
        # Call STT service
        if stt_client:
            # Create a temporary file-like object for the audio
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_file.flush()
                
                # Call STT service with file upload
                with open(temp_file.name, "rb") as audio_file:
                    files = {"audio": ("audio.m4a", audio_file, "audio/m4a")}
                    data = {"language": "en-US"}
                    
                    response = await stt_client.auth.make_authenticated_request(
                        "POST",
                        f"{STT_SERVICE_URL}/v1/transcribe",
                        files=files,
                        data=data,
                        timeout=30.0
                    )
                    
                    response.raise_for_status()
                    stt_result = response.json()
                    text = stt_result.get("text", "Could not transcribe audio")
                    
                # Clean up temp file
                import os
                os.unlink(temp_file.name)
        else:
            text = "STT service not available"
        
        # Process through AI
        reply = await generate_ai_response(text, {"caller": calling_service})
        
        # Call Kokoro TTS service  
        audio_b64 = None
        if tts_client and reply:
            try:
                logger.info(f"🎵 Generating speech with Kokoro TTS: '{reply[:50]}...'")
                
                audio_response = await tts_client.synthesize_speech(
                    text=reply,
                    voice="af_bella",  # Use default Kokoro voice
                    speed=1.0,
                    audio_encoding="MP3"
                )
                
                if audio_response:
                    audio_b64 = base64.b64encode(audio_response).decode()
                    logger.info(f"✅ Kokoro TTS audio generated: {len(audio_response)} bytes")
                else:
                    logger.error("❌ Kokoro TTS returned empty audio")
                    
            except Exception as tts_error:
                logger.error(f"❌ Kokoro TTS service call failed: {tts_error}")
        
        return {
            "transcription": text,
            "response_text": reply,
            "response_audio": audio_b64,
            "processed_by": "orchestrator",
            "caller": calling_service,
            "tts_engine": "kokoro"
        }
        
    except Exception as e:
        logger.error(f"Audio processing failed: {e}")
        return {"error": str(e)}

# -----------------------------------------------------------------------------
# Startup event
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Test service connectivity on startup"""
    if service_auth:
        logger.info("Testing service authentication...")
        try:
            token = await service_auth.get_access_token()
            logger.info("✅ Service authentication working")
        except Exception as e:
            logger.error(f"❌ Service authentication failed: {e}")
    
    if stt_client:
        logger.info("✅ STT client configured")
    else:
        logger.warning("⚠️ STT client not available")
    
    if tts_client:
        logger.info("✅ Kokoro TTS client configured")
        # Initialize Kokoro TTS and get available voices
        try:
            await tts_client.initialize()
        except Exception as e:
            logger.error(f"❌ Failed to initialize Kokoro TTS: {e}")
    else:
        logger.warning("⚠️ Kokoro TTS client not available")
    
    if ai_model:
        logger.info("✅ AI model configured and ready")
    else:
        logger.warning("⚠️ AI model not available - using fallback responses")

# Include existing voice router and other endpoints...