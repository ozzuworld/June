# June/services/june-orchestrator/app.py - FIXED EXTERNAL TTS INTEGRATION

import os
import json
import uuid
import asyncio
import logging
import time
import base64
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends

# Import the shared auth module
from shared.auth_service import create_service_auth_client, require_service_auth, ServiceAuthClient

# Import Firebase auth (keeping existing functionality)
from authz import get_current_user

# Import FIXED external TTS client
from external_tts_client import ExternalTTSClient

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="June Orchestrator", version="1.0.0")
voice_router = APIRouter()

logger = logging.getLogger("orchestrator.voice")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------------------------------------------------------------
# Environment - FIXED: Better env var handling
# -----------------------------------------------------------------------------
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_SHARED_SECRET", "")

# AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Service URLs - FIXED: Proper external TTS handling
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "")
EXTERNAL_TTS_URL = os.getenv("EXTERNAL_TTS_URL", "")

# FIXED: Decode base64 URL if needed
if EXTERNAL_TTS_URL:
    try:
        # Try to decode if it's base64 encoded
        decoded_url = base64.b64decode(EXTERNAL_TTS_URL).decode('utf-8')
        if decoded_url.startswith('http'):
            EXTERNAL_TTS_URL = decoded_url
            logger.info(f"✅ Decoded external TTS URL from base64")
    except Exception:
        # Use as-is if not base64 encoded
        pass

# Audio defaults
DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en-US")

# Initialize AI model (existing code remains the same)
ai_model = None
try:
    if GEMINI_API_KEY:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        
        genai.configure(api_key=GEMINI_API_KEY)
        
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

# -----------------------------------------------------------------------------
# FIXED: Enhanced STT Client with better error handling
# -----------------------------------------------------------------------------
class AuthenticatedSTTClient:
    """STT client with authentication and proper error handling"""
    
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
        self.is_available = True
        self.last_health_check = 0
    
    async def health_check(self) -> bool:
        """Check if STT service is available"""
        now = time.time()
        if now - self.last_health_check < 30:  # Cache for 30 seconds
            return self.is_available
        
        try:
            response = await self.auth.make_authenticated_request(
                "GET",
                f"{self.base_url}/healthz",
                timeout=5.0
            )
            self.is_available = response.status_code == 200
            self.last_health_check = now
            return self.is_available
        except Exception as e:
            logger.warning(f"STT health check failed: {e}")
            self.is_available = False
            self.last_health_check = now
            return False
    
    async def transcribe(self, audio_data: bytes, language: str = "en-US") -> dict:
        """Transcribe audio using STT service with fallback"""
        try:
            if not await self.health_check():
                return {"text": "STT service unavailable", "confidence": 0.0, "error": "service_unavailable"}
            
            response = await self.auth.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/transcribe",
                files={"audio": ("audio.m4a", audio_data, "audio/mp4")},
                data={"language": language},
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("text", "Could not transcribe audio"),
                    "confidence": result.get("confidence", 0.0),
                    "method": result.get("method", "unknown"),
                    "success": True
                }
            else:
                logger.error(f"STT service error: {response.status_code} - {response.text}")
                return {"text": "Transcription service error", "confidence": 0.0, "error": f"http_{response.status_code}", "success": False}
                
        except asyncio.TimeoutError:
            logger.error("STT service timeout")
            return {"text": "Transcription timeout", "confidence": 0.0, "error": "timeout", "success": False}
        except Exception as e:
            logger.error(f"STT client error: {e}")
            return {"text": "STT service error", "confidence": 0.0, "error": str(e), "success": False}

# -----------------------------------------------------------------------------
# Service authentication setup
# -----------------------------------------------------------------------------
try:
    service_auth = create_service_auth_client("orchestrator")
    logger.info("✅ Service authentication initialized")
except Exception as e:
    logger.warning(f"⚠️ Service authentication not available: {e}")
    service_auth = None

# Initialize client instances
stt_client = None
tts_client = None

# -----------------------------------------------------------------------------
# FIXED: Enhanced health check endpoint
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    """Enhanced health check endpoint"""
    health_status = {
        "ok": True,
        "service": "june-orchestrator",
        "timestamp": time.time(),
        "status": "healthy",
        "components": {
            "ai_model": ai_model is not None,
            "service_auth": service_auth is not None,
            "stt_client": stt_client is not None,
            "tts_client": tts_client is not None,
            "external_tts_url": EXTERNAL_TTS_URL != ""
        },
        "tts_type": "external-openvoice"
    }
    
    # Check external dependencies
    if stt_client:
        health_status["components"]["stt_available"] = await stt_client.health_check()
    
    if tts_client:
        try:
            health_status["components"]["external_tts_available"] = await tts_client.health_check()
        except Exception:
            health_status["components"]["external_tts_available"] = False
    
    # Overall health based on critical components
    critical_components = ["ai_model", "service_auth", "stt_client"]
    health_status["ok"] = all(health_status["components"].get(comp, False) for comp in critical_components)
    
    if not health_status["ok"]:
        health_status["status"] = "degraded"
    
    return health_status

# -----------------------------------------------------------------------------
# FIXED: Enhanced process_audio endpoint with proper error handling
# -----------------------------------------------------------------------------
@app.post("/v1/process-audio")
async def process_audio(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """FIXED: Process audio through STT -> AI -> External TTS pipeline with proper error handling"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"🎤 Audio processing request from service: {calling_service}")
    
    # Initialize response structure
    response = {
        "transcription": "",
        "transcription_confidence": 0.0,
        "response_text": "",
        "response_audio": None,
        "processed_by": "orchestrator",
        "caller": calling_service,
        "processing_complete": False,
        "has_audio": False,
        "errors": [],
        "warnings": []
    }
    
    audio_data = payload.get("audio_data")  # base64 encoded audio
    if not audio_data:
        response["errors"].append("No audio data provided")
        response["response_text"] = "Please provide audio data"
        return response
    
    try:
        # Decode audio
        try:
            audio_bytes = base64.b64decode(audio_data)
            logger.info(f"📊 Received audio: {len(audio_bytes)} bytes")
        except Exception as decode_error:
            response["errors"].append(f"Audio decode error: {decode_error}")
            response["response_text"] = "Invalid audio data format"
            return response
        
        # Step 1: Call STT service with proper error handling
        transcription_result = {"text": "Could not transcribe audio", "confidence": 0.0, "success": False}
        
        if stt_client:
            try:
                transcription_result = await stt_client.transcribe(audio_bytes, "en-US")
                if transcription_result.get("success", False):
                    logger.info(f"✅ STT transcription: '{transcription_result['text']}' (confidence: {transcription_result['confidence']})")
                else:
                    response["warnings"].append(f"STT failed: {transcription_result.get('error', 'unknown')}")
                    logger.warning(f"⚠️ STT failed: {transcription_result.get('error', 'unknown')}")
            except Exception as stt_error:
                response["warnings"].append(f"STT service call failed: {stt_error}")
                logger.error(f"❌ STT service call failed: {stt_error}")
        else:
            response["warnings"].append("STT client not available")
            logger.warning("⚠️ STT client not available")
        
        # Use transcription or fallback
        transcription_text = transcription_result.get("text", "Hello, how can I help you?")
        transcription_confidence = transcription_result.get("confidence", 0.0)
        
        response["transcription"] = transcription_text
        response["transcription_confidence"] = transcription_confidence
        
        # Step 2: Process through AI
        try:
            ai_reply = await generate_ai_response(transcription_text, {"caller": calling_service})
            response["response_text"] = ai_reply
            logger.info(f"🤖 AI response: '{ai_reply[:100]}...'")
        except Exception as ai_error:
            response["errors"].append(f"AI processing failed: {ai_error}")
            response["response_text"] = f"I'm having trouble processing your request. You said: '{transcription_text}'"
            logger.error(f"❌ AI processing failed: {ai_error}")
        
        # Step 3: Generate TTS audio via external service (with fallback)
        if tts_client and response["response_text"]:
            try:
                logger.info(f"🎵 Generating speech via external TTS: '{response['response_text'][:50]}...'")
                
                audio_response = await tts_client.synthesize_speech(
                    text=response["response_text"],
                    voice="default",
                    speed=1.0,
                    language="EN"
                )
                
                if audio_response:
                    response["response_audio"] = base64.b64encode(audio_response).decode('utf-8')
                    response["has_audio"] = True
                    logger.info(f"✅ External TTS success: {len(audio_response)} bytes")
                else:
                    response["warnings"].append("External TTS returned empty audio")
                    logger.warning("⚠️ External TTS returned empty audio")
                    
            except Exception as tts_error:
                response["warnings"].append(f"External TTS failed: {tts_error}")
                logger.error(f"❌ External TTS failed: {tts_error}")
        else:
            if not tts_client:
                response["warnings"].append("External TTS client not available")
                logger.warning("⚠️ External TTS client not available")
        
        # Mark as complete
        response["processing_complete"] = True
        response["ai_model"] = "gemini-1.5-flash" if ai_model else "fallback"
        response["tts_engine"] = "external-openvoice" if response["has_audio"] else None
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Audio processing failed: {e}", exc_info=True)
        
        response["errors"].append(f"Processing failed: {str(e)}")
        response["response_text"] = "I apologize, but I encountered an error processing your audio. Please try again."
        return response

# -----------------------------------------------------------------------------
# FIXED: Startup event with better dependency management
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize all service clients on startup with proper error handling"""
    global stt_client, tts_client
    
    if service_auth:
        logger.info("🔧 Initializing service clients...")
        
        # Test service authentication
        try:
            token = await service_auth.get_access_token()
            logger.info("✅ Service authentication working")
        except Exception as e:
            logger.error(f"❌ Service authentication failed: {e}")
            # Continue startup but mark as degraded
        
        # Initialize STT client
        if STT_SERVICE_URL:
            try:
                stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
                logger.info(f"✅ STT client configured: {STT_SERVICE_URL}")
            except Exception as e:
                logger.error(f"❌ STT client initialization failed: {e}")
        else:
            logger.warning("⚠️ STT_SERVICE_URL not set")
        
        # Initialize External TTS client
        if EXTERNAL_TTS_URL:
            try:
                tts_client = ExternalTTSClient(EXTERNAL_TTS_URL, service_auth)
                logger.info(f"✅ External TTS client configured: {EXTERNAL_TTS_URL}")
                
                # Test external TTS connectivity
                try:
                    await tts_client.health_check()
                    logger.info("✅ External TTS service connectivity verified")
                except Exception as health_error:
                    logger.warning(f"⚠️ External TTS health check failed: {health_error}")
                    
            except Exception as e:
                logger.error(f"❌ External TTS client initialization failed: {e}")
                tts_client = None
        else:
            tts_client = None
            logger.warning("⚠️ EXTERNAL_TTS_URL not set - TTS disabled")
    else:
        logger.warning("⚠️ Service authentication not available")
    
    # Summary
    logger.info(f"""
    🚀 Orchestrator started:
    - STT: {'✅' if stt_client else '❌'} ({STT_SERVICE_URL or 'not configured'})
    - TTS: {'✅' if tts_client else '❌'} (External: {EXTERNAL_TTS_URL or 'not configured'})
    - AI: {'✅' if ai_model else '❌'} ({'Gemini' if ai_model else 'fallback mode'})
    - Auth: {'✅' if service_auth else '❌'}
    """)

# Keep existing generate_ai_response function and other endpoints unchanged
async def generate_ai_response(user_input: str, user_context: dict = None) -> str:
    """Generate AI response using Gemini"""
    if not ai_model:
        return f"I received your message: '{user_input}'. However, AI is currently not configured. This is a placeholder response."
    
    try:
        system_prompt = """You are June, a helpful AI assistant. You are knowledgeable, friendly, and concise. 
        You can help with various tasks, answer questions, and have engaging conversations.
        
        Key traits:
        - Be helpful and informative
        - Keep responses conversational and engaging
        - If you don't know something, say so honestly
        - Be concise but thorough when needed
        """
        
        full_prompt = f"{system_prompt}\n\nUser: {user_input}\n\nJune:"
        
        response = ai_model.generate_content(full_prompt)
        
        if response.text:
            return response.text.strip()
        else:
            return "I'm having trouble generating a response right now. Could you try rephrasing your question?"
            
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        return f"I'm experiencing some technical difficulties. Here's what I can tell you about '{user_input}': I'd be happy to help, but I'm having trouble processing that right now."