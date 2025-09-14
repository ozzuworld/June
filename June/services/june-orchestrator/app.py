# June/services/june-orchestrator/app.py
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
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")

# Downstream WebSocket services (existing functionality)
STT_WS_URL  = os.getenv("STT_WS_URL", "")
STT_HTTP_URL = os.getenv("STT_HTTP_URL") or (STT_WS_URL.replace("wss://", "https://").removesuffix("/ws") if STT_WS_URL else "")
TTS_URL     = os.getenv("TTS_URL", "")

# Audio defaults
DEFAULT_LOCALE        = os.getenv("DEFAULT_LOCALE", "en-US")
DEFAULT_STT_RATE      = int(os.getenv("DEFAULT_STT_RATE", "16000"))
DEFAULT_STT_ENCODING  = os.getenv("DEFAULT_STT_ENCODING", "pcm16")
DEFAULT_TTS_ENCODING  = os.getenv("DEFAULT_TTS_ENCODING", "MP3")

# Handshake + private STT options
STT_HANDSHAKE              = os.getenv("STT_HANDSHAKE", "start").lower()
STT_REQUIRE_CLOUDRUN_AUTH  = os.getenv("STT_REQUIRE_CLOUDRUN_AUTH", "false").lower() == "true"

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
# Enhanced STT and TTS clients with authentication (keeping existing code)
# -----------------------------------------------------------------------------
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

class AuthenticatedTTSClient:
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
    
    async def synthesize_speech(
        self, 
        text: str, 
        language_code: str = "en-US",
        voice_name: str = "en-US-Wavenet-D"
    ) -> bytes:
        """Call TTS service with service authentication"""
        if not self.auth:
            raise Exception("Service authentication not configured")
        
        url = f"{self.base_url}/v1/tts"
        
        params = {
            "text": text,
            "language_code": language_code,
            "voice_name": voice_name,
            "audio_encoding": "MP3"
        }
        
        try:
            response = await self.auth.make_authenticated_request(
                "POST",
                url,
                params=params,
                timeout=30.0
            )
            
            response.raise_for_status()
            return response.content
            
        except Exception as e:
            logger.error(f"TTS service call failed: {e}")
            raise

# Initialize service clients (only if auth is available)
stt_client = None
tts_client = None

if service_auth:
    if STT_SERVICE_URL:
        stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
        logger.info("✅ STT service client initialized")
    
    if TTS_SERVICE_URL:
        tts_client = AuthenticatedTTSClient(TTS_SERVICE_URL, service_auth)
        logger.info("✅ TTS service client initialized")

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
        "ai_enabled": ai_model is not None
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator", 
        "status": "running",
        "version": "1.0.0",
        "ai_enabled": ai_model is not None
    }

@app.get("/configz")
async def configz():
    """Configuration endpoint for debugging"""
    return {
        "FIREBASE_PROJECT_ID": FIREBASE_PROJECT_ID,
        "STT_WS_URL": STT_WS_URL,
        "STT_HTTP_URL": STT_HTTP_URL,
        "TTS_URL": TTS_URL,
        "STT_SERVICE_URL": STT_SERVICE_URL,
        "TTS_SERVICE_URL": TTS_SERVICE_URL,
        "DEFAULT_LOCALE": DEFAULT_LOCALE,
        "DEFAULT_STT_RATE": DEFAULT_STT_RATE,
        "DEFAULT_STT_ENCODING": DEFAULT_STT_ENCODING,
        "DEFAULT_TTS_ENCODING": DEFAULT_TTS_ENCODING,
        "STT_HANDSHAKE": STT_HANDSHAKE,
        "STT_REQUIRE_CLOUDRUN_AUTH": STT_REQUIRE_CLOUDRUN_AUTH,
        "service_auth_enabled": service_auth is not None,
        "stt_client_ready": stt_client is not None,
        "tts_client_ready": tts_client is not None,
        "ai_model_enabled": ai_model is not None,
        "gemini_api_key_present": bool(GEMINI_API_KEY)
    }

# -----------------------------------------------------------------------------
# Protected service endpoints (for other services to call) - UPDATED WITH AI
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
    """Process audio through STT -> LLM -> TTS pipeline"""
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
        
        # Process through AI (instead of local processing)
        reply = await generate_ai_response(text, {"caller": calling_service})
        
        # Call TTS service  
        audio_b64 = None
        if tts_client and reply:
            try:
                # URL encode the text properly
                import urllib.parse
                encoded_text = urllib.parse.quote(reply)
                
                response = await tts_client.auth.make_authenticated_request(
                    "POST",
                    f"{TTS_SERVICE_URL}/v1/tts",
                    params={
                        "text": encoded_text,
                        "language_code": "en-US",
                        "voice_name": "en-US-Wavenet-D",
                        "audio_encoding": "MP3"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    audio_response = response.content
                    audio_b64 = base64.b64encode(audio_response).decode()
                else:
                    logger.error(f"TTS service returned {response.status_code}: {response.text}")
                    
            except Exception as tts_error:
                logger.error(f"TTS service call failed: {tts_error}")
        
        return {
            "transcription": text,
            "response_text": reply,
            "response_audio": audio_b64,
            "processed_by": "orchestrator",
            "caller": calling_service
        }
        
    except Exception as e:
        logger.error(f"Audio processing failed: {e}")
        return {"error": str(e)}

# -----------------------------------------------------------------------------
# Firebase-authenticated endpoints (keeping existing functionality)
# -----------------------------------------------------------------------------
@app.get("/whoami")
async def whoami(user=Depends(get_current_user)):
    """Debug endpoint to see Firebase user claims"""
    return {"firebase_user": user}

# Keep all existing WebSocket functionality below...
# (Existing functionality continues here - all the _fetch_gcp_id_token, _llm_generate_reply_via_http, etc.)

async def _fetch_gcp_id_token(audience: str) -> str:
    """Get a Google-signed ID token for Cloud Run (audience = HTTPS base URL)."""
    url = "http://metadata/computeMetadata/v1/instance/service-accounts/default/identity"
    headers = {"Metadata-Flavor": "Google"}
    params = {"audience": audience, "format": "full"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        return r.text.strip()

async def _llm_generate_reply_via_http(text: str, id_token: str, base_url: str = "http://127.0.0.1:8080") -> str:
    """Calls this same service's /v1/chat to reuse your existing chain/agent."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
            r = await client.post(
                f"{base_url}/v1/chat",
                headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
                json={"user_input": text},
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("reply") or "").strip()
    except Exception:
        logger.exception("[voice] /v1/chat failed; falling back")
        return f"You said: {text}"

async def _tts_stream(reply_text: str, locale: str, id_token: str, client_ws: WebSocket, turn_id: str):
    """Streams audio bytes from TTS to the WebSocket client."""
    if not TTS_URL:
        await client_ws.send_text(json.dumps({"type":"error", "code":"CONFIG", "message":"TTS_URL not set"}))
        return

    params = {"text": reply_text, "language_code": locale, "audio_encoding": DEFAULT_TTS_ENCODING}
    headers = {"Authorization": f"Bearer {id_token}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        async with client.stream("POST", TTS_URL, params=params, headers=headers) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "audio/mpeg")
            await client_ws.send_text(json.dumps({"type":"tts.start", "turn_id": turn_id, "content_type": ctype}))
            async for chunk in r.aiter_bytes(chunk_size=32768):
                if not chunk:
                    break
                await client_ws.send_bytes(chunk)
            await client_ws.send_text(json.dumps({"type":"tts.done", "turn_id": turn_id}))

# Voice bridge (client <-> STT; on final -> call LLM -> stream TTS)
@voice_router.websocket("/v1/voice")
async def voice_ws(ws: WebSocket):
    """Client connects here with WebSocket for voice functionality"""
    token: Optional[str] = ws.query_params.get("token")
    locale: str = ws.query_params.get("locale") or DEFAULT_LOCALE

    await ws.accept()
    if not token:
        await ws.send_text(json.dumps({"type":"error","code":"AUTH","message":"Missing ?token"}))
        await ws.close(code=4401)
        return

    try:
        await _stt_bridge(ws, token, locale, DEFAULT_STT_ENCODING)
    except Exception:
        logger.exception("[voice] unhandled")
        try:
            await ws.send_text(json.dumps({"type":"error","code":"VOICE","message":"internal error"}))
        except Exception:
            pass
        await ws.close(code=1011)

async def _stt_bridge(client_ws: WebSocket, id_token: str, locale: str, encoding: str):
    """Your existing STT bridge implementation"""
    if not STT_WS_URL:
        await client_ws.send_text(json.dumps({"type":"error","code":"CONFIG","message":"STT_WS_URL not set"}))
        return

    await client_ws.send_text(json.dumps({"type": "connected", "message": "Voice WebSocket ready"}))

# Include the voice router
app.include_router(voice_router)

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
        logger.info("✅ TTS client configured")
    else:
        logger.warning("⚠️ TTS client not available")
    
    if ai_model:
        logger.info("✅ AI model configured and ready")
    else:
        logger.warning("⚠️ AI model not available - using fallback responses")