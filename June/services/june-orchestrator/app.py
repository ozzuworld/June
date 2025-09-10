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
# Service authentication setup
# -----------------------------------------------------------------------------
try:
    service_auth = create_service_auth_client("orchestrator")
    logger.info("✅ Service authentication initialized")
except Exception as e:
    logger.warning(f"⚠️ Service authentication not available: {e}")
    service_auth = None

# -----------------------------------------------------------------------------
# Enhanced STT and TTS clients with authentication
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
# Health and config endpoints (FIXED - no duplicates)
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-orchestrator", 
        "timestamp": time.time(),
        "status": "healthy"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator", 
        "status": "running",
        "version": "1.0.0"
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
        "tts_client_ready": tts_client is not None
    }

# -----------------------------------------------------------------------------
# Protected service endpoints (for other services to call)
# -----------------------------------------------------------------------------
@app.post("/v1/chat")
async def chat(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Chat endpoint protected by service authentication"""
    user_text = (payload or {}).get("user_input", "")
    calling_service = service_auth_data.get("client_id", "unknown")
    
    logger.info(f"Chat request from service: {calling_service}")
    
    # TODO: plug your LLM/agent here; for now, simple echo-style reply
    reply = f"You said: {user_text}".strip()
    return {"reply": reply, "processed_by": "orchestrator", "caller": calling_service}

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
            stt_result = await stt_client.transcribe_audio(audio_bytes)
            text = stt_result.get("text", "")
        else:
            text = "STT service not available"
        
        # Process through LLM (local processing)
        reply = f"You said: {text}. Here's my response!"
        
        # Call TTS service  
        if tts_client:
            audio_response = await tts_client.synthesize_speech(reply)
            audio_b64 = base64.b64encode(audio_response).decode()
        else:
            audio_b64 = None
        
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
# Existing functionality - keep all your original WebSocket and helper code
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Voice bridge (client <-> STT; on final -> call LLM -> stream TTS)
# Keep all your existing WebSocket code here
# -----------------------------------------------------------------------------
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
    """Keep your existing STT bridge implementation"""
    if not STT_WS_URL:
        await client_ws.send_text(json.dumps({"type":"error","code":"CONFIG","message":"STT_WS_URL not set"}))
        return

    # Your existing WebSocket STT bridge code goes here...
    # I'm keeping this minimal to focus on the service auth changes
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