# June/services/june-orchestrator/app.py - UPDATED FOR EXTERNAL TTS
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

# Import external TTS client
from external_tts_client import ExternalTTSClient

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

# Service URLs
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "")
EXTERNAL_TTS_URL = os.getenv("EXTERNAL_TTS_URL", "")

# Audio defaults
DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en-US")

# -----------------------------------------------------------------------------
# Service client classes
# -----------------------------------------------------------------------------

class AuthenticatedSTTClient:
    """STT client with authentication"""
    
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
    
    async def transcribe(self, audio_data: bytes, language: str = "en-US") -> dict:
        """Transcribe audio using STT service"""
        try:
            response = await self.auth.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/transcribe",
                files={"audio": ("audio.m4a", audio_data, "audio/mp4")},
                data={"language": language},
                timeout=30.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"STT service error: {response.status_code}")
                return {"text": "Could not transcribe audio", "confidence": 0.0}
                
        except Exception as e:
            logger.error(f"STT client error: {e}")
            return {"text": "STT service unavailable", "confidence": 0.0}

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

# Initialize client instances (will be set in startup)
stt_client = None
tts_client = None

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
        "tts_type": "external-openvoice"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator", 
        "status": "running",
        "version": "1.0.0",
        "ai_enabled": ai_model is not None,
        "tts_type": "external-openvoice"
    }

@app.get("/configz")
async def configz():
    """Configuration endpoint for debugging"""
    return {
        "FIREBASE_PROJECT_ID": FIREBASE_PROJECT_ID,
        "STT_SERVICE_URL": STT_SERVICE_URL,
        "EXTERNAL_TTS_URL": EXTERNAL_TTS_URL,
        "DEFAULT_LOCALE": DEFAULT_LOCALE,
        "service_auth_enabled": service_auth is not None,
        "stt_client_ready": stt_client is not None,
        "tts_client_ready": tts_client is not None,
        "tts_type": "external-openvoice",
        "ai_model_enabled": ai_model is not None,
        "gemini_api_key_present": bool(GEMINI_API_KEY),
    }

# -----------------------------------------------------------------------------
# Protected service endpoints
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
            "ai_model": "gemini-1.5-flash" if ai_model else "fallback",
            "tts_type": "external-openvoice"
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
    """Process audio through STT -> AI -> External TTS pipeline"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"🎤 Audio processing request from service: {calling_service}")
    
    audio_data = payload.get("audio_data")  # base64 encoded audio
    if not audio_data:
        return {
            "error": "No audio data provided",
            "transcription": "",
            "response_text": "Please provide audio data",
            "response_audio": None
        }
    
    try:
        # Decode audio
        import base64
        audio_bytes = base64.b64decode(audio_data)
        logger.info(f"📊 Received audio: {len(audio_bytes)} bytes")
        
        # Step 1: Call STT service
        transcription_text = "Could not transcribe audio"
        stt_confidence = 0.0
        
        if stt_client:
            try:
                stt_result = await stt_client.transcribe(audio_bytes, "en-US")
                transcription_text = stt_result.get("text", "Could not transcribe audio")
                stt_confidence = stt_result.get("confidence", 0.0)
                logger.info(f"✅ STT transcription: '{transcription_text}' (confidence: {stt_confidence})")
            except Exception as stt_error:
                logger.error(f"❌ STT service call failed: {stt_error}")
        else:
            logger.warning("⚠️ STT client not available")
        
        # If transcription failed, provide fallback
        if not transcription_text or transcription_text in ["Could not transcribe audio", "Speech recognition failed"]:
            transcription_text = "Hello, how can I help you?"
            logger.warning(f"⚠️ Using fallback transcription: '{transcription_text}'")
        
        # Step 2: Process through AI
        reply = await generate_ai_response(transcription_text, {"caller": calling_service})
        logger.info(f"🤖 AI response: '{reply[:100]}...'")
        
        # Step 3: Generate TTS audio via external service
        audio_b64 = None
        tts_metadata = {}
        
        if tts_client and reply:
            try:
                logger.info(f"🎵 Generating speech via external TTS: '{reply[:50]}...'")
                
                # Call external TTS service
                audio_response = await tts_client.synthesize_speech(
                    text=reply,
                    voice="default",  # Use your OpenVoice voice names
                    speed=1.0,
                    language="EN"
                )
                
                if audio_response:
                    # Encode audio to base64 for response
                    audio_b64 = base64.b64encode(audio_response).decode('utf-8')
                    logger.info(f"✅ External TTS success: {len(audio_response)} bytes")
                    
                    tts_metadata = {
                        "voice": "openvoice",
                        "engine": "external-openvoice",
                        "service": "external"
                    }
                else:
                    logger.error("❌ External TTS returned empty audio")
                    
            except Exception as tts_error:
                logger.error(f"❌ External TTS failed: {tts_error}")
        else:
            if not tts_client:
                logger.warning("⚠️ External TTS client not available")
            if not reply:
                logger.warning("⚠️ No reply text to synthesize")
        
        # Step 4: Return complete response
        return {
            "transcription": transcription_text,
            "transcription_confidence": stt_confidence,
            "response_text": reply,
            "response_audio": audio_b64,
            "processed_by": "orchestrator",
            "caller": calling_service,
            "ai_model": "gemini-1.5-flash" if ai_model else "fallback",
            "tts_engine": "external-openvoice" if audio_b64 else None,
            "tts_metadata": tts_metadata,
            "processing_complete": True,
            "has_audio": audio_b64 is not None
        }
        
    except Exception as e:
        logger.error(f"❌ Audio processing failed: {e}", exc_info=True)
        
        return {
            "error": str(e),
            "transcription": "Error processing audio",
            "response_text": "I apologize, but I encountered an error processing your audio. Please try again or use text input instead.",
            "response_audio": None,
            "processed_by": "orchestrator",
            "caller": calling_service,
            "processing_complete": False,
            "has_audio": False
        }

# -----------------------------------------------------------------------------
# Startup event - UPDATED FOR EXTERNAL TTS
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize all service clients on startup"""
    global stt_client, tts_client
    
    if service_auth:
        logger.info("🔧 Initializing service clients...")
        
        try:
            # Test service authentication
            token = await service_auth.get_access_token()
            logger.info("✅ Service authentication working")
        except Exception as e:
            logger.error(f"❌ Service authentication failed: {e}")
        
        # Initialize STT client
        if STT_SERVICE_URL:
            stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
            logger.info(f"✅ STT client configured: {STT_SERVICE_URL}")
        else:
            logger.warning("⚠️ STT_SERVICE_URL not set")
        
        # Initialize External TTS client
        if EXTERNAL_TTS_URL:
            tts_client = ExternalTTSClient(EXTERNAL_TTS_URL, service_auth)
            logger.info(f"✅ External TTS client configured: {EXTERNAL_TTS_URL}")
        else:
            tts_client = None
            logger.warning("⚠️ EXTERNAL_TTS_URL not set - TTS disabled")
    else:
        logger.warning("⚠️ Service authentication not available")
    
    # Test AI model
    if ai_model:
        logger.info("✅ Gemini AI model configured and ready")
    else:
        logger.warning("⚠️ AI model not available - using fallback responses")
    
    logger.info(f"""
    🚀 Orchestrator started:
    - STT: {stt_client is not None}
    - TTS: {tts_client is not None} (External OpenVoice)
    - AI: {ai_model is not None}
    - Auth: {service_auth is not None}
    """)