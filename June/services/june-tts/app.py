# File: June/services/june-tts/app.py
# Fixed version using travisvn/chatterbox-tts-api proxy approach

import os
import time
import logging
import asyncio
import subprocess
import signal
import sys
from typing import Optional, Dict, Any
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import auth modules (keep existing)
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="June Chatterbox TTS Service", version="1.0.0")

# Configuration
CHATTERBOX_API_PORT = 4123
CHATTERBOX_API_URL = f"http://localhost:{CHATTERBOX_API_PORT}"
WRAPPER_PORT = int(os.getenv("PORT", "8080"))

# Global process handle for the chatterbox API
chatterbox_process = None

class ChatterboxService:
    def __init__(self):
        self.is_ready = False
        self.api_url = CHATTERBOX_API_URL
        
    async def start_chatterbox_api(self):
        """Start the chatterbox-tts-api server in the background"""
        global chatterbox_process
        
        try:
            logger.info("🚀 Starting Chatterbox TTS API...")
            
            # Set environment variables for chatterbox API
            env = os.environ.copy()
            env.update({
                "HOST": "127.0.0.1",
                "PORT": str(CHATTERBOX_API_PORT),
                "DEVICE": os.getenv("DEVICE", "cpu"),
                "LOG_LEVEL": "INFO",
            })
            
            # Start the chatterbox API process
            chatterbox_process = subprocess.Popen([
                "python", "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1",
                "--port", str(CHATTERBOX_API_PORT),
                "--workers", "1"
            ], env=env, cwd="/app")
            
            # Wait for the API to be ready
            await self.wait_for_ready()
            
        except Exception as e:
            logger.error(f"❌ Failed to start Chatterbox API: {e}")
            raise
    
    async def wait_for_ready(self, timeout=300):
        """Wait for the chatterbox API to be ready"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{self.api_url}/health", timeout=5.0)
                    if response.status_code == 200:
                        self.is_ready = True
                        logger.info("✅ Chatterbox API is ready!")
                        return
            except Exception:
                pass
            
            await asyncio.sleep(2)
        
        raise TimeoutError("❌ Chatterbox API failed to start within timeout")
    
    async def proxy_request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Proxy request to the chatterbox API"""
        if not self.is_ready:
            raise HTTPException(status_code=503, detail="Chatterbox API not ready")
        
        url = f"{self.api_url}{endpoint}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, **kwargs)
            return response

# Global service instance
chatterbox_service = ChatterboxService()

# Keep existing Pydantic models
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    language: str = Field("en", description="Language code")
    exaggeration: float = Field(0.5, ge=0.0, le=1.0, description="Emotion exaggeration")
    cfg_weight: float = Field(0.5, ge=0.0, le=1.0, description="Config weight")
    temperature: float = Field(1.0, ge=0.5, le=2.0, description="Temperature")

# Keep existing endpoints but update implementation
@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    startup_time = time.time() - getattr(app.state, 'startup_time', time.time())
    
    return {
        "ok": True,
        "service": "june-chatterbox-tts",
        "timestamp": time.time(),
        "status": "healthy" if chatterbox_service.is_ready else "initializing",
        "chatterbox_available": chatterbox_service.is_ready,
        "device": os.getenv("DEVICE", "cpu"),
        "supported_languages": [
            "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
            "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
            "sw", "tr", "zh"
        ],
        "engine": "chatterbox-travisvn",
        "startup_time": startup_time,
        "features": {
            "emotion_control": True,
            "voice_cloning": True,
            "multilingual": True,
            "watermarking": True
        }
    }

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    app.state.startup_time = time.time()
    logger.info("🚀 Starting Chatterbox TTS Service...")
    
    try:
        await chatterbox_service.start_chatterbox_api()
        logger.info("✅ Service ready")
    except Exception as e:
        logger.error(f"❌ Service failed to initialize: {e}")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-chatterbox-tts",
        "status": "running",
        "engine": "chatterbox-travisvn",
        "version": "1.0.0",
        "license": "MIT",
        "chatterbox_available": chatterbox_service.is_ready
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voice profiles"""
    try:
        if chatterbox_service.is_ready:
            response = await chatterbox_service.proxy_request("GET", "/v1/voices")
            return response.json()
    except Exception as e:
        logger.error(f"Failed to get voices from API: {e}")
    
    # Fallback response
    return {
        "voices": {
            "assistant_female": {"name": "Assistant Female", "description": "Default female voice"},
            "assistant_male": {"name": "Assistant Male", "description": "Default male voice"}
        },
        "default": "assistant_female",
        "engine": "chatterbox-travisvn"
    }

@app.get("/v1/languages")
async def list_languages():
    """List supported languages"""
    return {
        "languages": [
            "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
            "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
            "sw", "tr", "zh"
        ],
        "default_language": "en",
        "engine": "chatterbox-travisvn"
    }

# Main TTS endpoint (keep same interface for orchestrator compatibility)
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("assistant_female", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_encoding: str = Query("MP3", description="Audio format"),
    language: str = Query("en", description="Language code"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """TTS endpoint for service-to-service communication (orchestrator compatible)"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:50]}...'")
        
        if not chatterbox_service.is_ready:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Convert parameters to chatterbox API format
        cfg_weight = 1.0 / speed if speed > 0 else 0.5
        cfg_weight = max(0.1, min(1.0, cfg_weight))
        
        # Call chatterbox API using OpenAI-compatible endpoint
        response = await chatterbox_service.proxy_request(
            "POST",
            "/v1/audio/speech",
            json={
                "input": text,
                "voice": voice,
                "exaggeration": 0.5,
                "cfg_weight": cfg_weight,
                "temperature": 1.0,
                "language": language if language != "en" else None
            }
        )
        
        response.raise_for_status()
        
        # Determine media type
        media_type = "audio/mpeg" if audio_encoding.upper() == "MP3" else "audio/wav"
        
        logger.info(f"✅ Chatterbox synthesis successful: {len(response.content)} bytes")
        
        return StreamingResponse(
            iter([response.content]),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{audio_encoding.lower()}",
                "X-TTS-Engine": "chatterbox-travisvn",
                "X-Caller-Service": calling_service,
                "X-Features": "emotion-control,voice-cloning,watermarking"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Advanced TTS endpoint
@app.post("/v1/tts/advanced")
async def synthesize_speech_advanced(
    request: TTSRequest,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Advanced TTS endpoint with full Chatterbox emotion control"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎭 Advanced TTS request from {calling_service}")
        
        if not chatterbox_service.is_ready:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Call chatterbox API with advanced parameters
        response = await chatterbox_service.proxy_request(
            "POST",
            "/v1/audio/speech",
            json={
                "input": request.text,
                "voice": "assistant_female",
                "exaggeration": request.exaggeration,
                "cfg_weight": request.cfg_weight,
                "temperature": request.temperature,
                "language": request.language if request.language != "en" else None
            }
        )
        
        response.raise_for_status()
        
        logger.info(f"✅ Advanced synthesis successful")
        
        return StreamingResponse(
            iter([response.content]),
            media_type="audio/wav",
            headers={
                "X-TTS-Engine": "chatterbox-travisvn",
                "X-Language": request.language,
                "X-Caller-Service": calling_service,
                "X-Emotion-Config": f"exag={request.exaggeration},cfg={request.cfg_weight},temp={request.temperature}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Advanced synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Voice cloning endpoint
@app.post("/v1/tts/clone")
async def voice_clone_synthesis(
    text: str = Form(..., description="Text to synthesize"),
    language: str = Form("en", description="Language code"),
    exaggeration: float = Form(0.5, description="Emotion exaggeration"),
    cfg_weight: float = Form(0.5, description="Config weight"),
    temperature: float = Form(1.0, description="Temperature"),
    reference_audio: UploadFile = File(..., description="Reference audio file"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning endpoint using reference audio"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎤 Voice cloning request from {calling_service}")
        
        if not chatterbox_service.is_ready:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Read reference audio
        reference_audio_data = await reference_audio.read()
        
        # Call chatterbox API with voice cloning
        files = {"voice_sample": ("reference.wav", reference_audio_data, "audio/wav")}
        data = {
            "input": text,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
            "temperature": temperature,
            "language": language if language != "en" else None
        }
        
        response = await chatterbox_service.proxy_request(
            "POST",
            "/v1/audio/speech",
            files=files,
            data=data
        )
        
        response.raise_for_status()
        
        logger.info(f"✅ Voice cloning successful")
        
        return StreamingResponse(
            iter([response.content]),
            media_type="audio/wav",
            headers={
                "X-TTS-Engine": "chatterbox-travisvn",
                "X-Feature": "voice-cloning",
                "X-Language": language,
                "X-Caller-Service": calling_service,
                "X-Reference-Audio-Size": str(len(reference_audio_data))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Shutdown handler
@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown"""
    global chatterbox_process
    
    logger.info("🛑 Shutting down June Chatterbox TTS Service...")
    
    if chatterbox_process:
        try:
            chatterbox_process.terminate()
            chatterbox_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chatterbox_process.kill()
        except Exception as e:
            logger.error(f"Error stopping chatterbox process: {e}")

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    global chatterbox_process
    
    if chatterbox_process:
        try:
            chatterbox_process.terminate()
            chatterbox_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chatterbox_process.kill()
    
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting June Chatterbox TTS Service on port {WRAPPER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=WRAPPER_PORT, workers=1)