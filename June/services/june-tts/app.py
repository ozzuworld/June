# June/services/june-tts/app.py - PRODUCTION CHATTERBOX TTS API
import os
import time
import logging
import base64
import httpx
import json
from typing import Optional, Dict, Any
from io import BytesIO

from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June TTS Service", 
    version="2.0.0",
    description="Production TTS using Chatterbox API by travisvn"
)

# Configuration from environment
CHATTERBOX_API_URL = os.getenv("CHATTERBOX_API_URL", "http://localhost:8000")
CHATTERBOX_API_KEY = os.getenv("CHATTERBOX_API_KEY", "")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "af_bella")
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "1.0"))
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.3"))
DEFAULT_EXAGGERATION = float(os.getenv("DEFAULT_EXAGGERATION", "0.5"))
ENABLE_VOICE_CLONING = os.getenv("ENABLE_VOICE_CLONING", "true").lower() == "true"

# Available voices in Chatterbox
CHATTERBOX_VOICES = {
    "af_bella": "Bella - Warm, friendly female voice",
    "af_nicole": "Nicole - Professional female voice", 
    "af_sarah": "Sarah - Energetic female voice",
    "af_sky": "Sky - Calm, soothing female voice",
    "am_adam": "Adam - Professional male voice",
    "am_michael": "Michael - Friendly male voice",
    "bf_emma": "Emma - British female voice",
    "bf_isabella": "Isabella - Elegant female voice",
    "bm_george": "George - British male voice",
    "bm_lewis": "Lewis - Casual male voice"
}

class ChatterboxClient:
    """Client for interacting with Chatterbox TTS API"""
    
    def __init__(self):
        self.base_url = CHATTERBOX_API_URL.rstrip('/')
        self.api_key = CHATTERBOX_API_KEY
        self.client = None
        self._ensure_client()
    
    def _ensure_client(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=60.0)
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def health_check(self) -> bool:
        """Check if Chatterbox API is healthy"""
        try:
            self._ensure_client()
            response = await self.client.get(
                f"{self.base_url}/health",
                headers=self._get_headers(),
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        temperature: float = DEFAULT_TEMPERATURE,
        exaggeration: float = DEFAULT_EXAGGERATION,
        response_format: str = "mp3"
    ) -> bytes:
        """Synthesize speech using Chatterbox API"""
        try:
            self._ensure_client()
            
            # Use OpenAI-compatible endpoint
            payload = {
                "model": "chatterbox",
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": response_format,
                # Chatterbox-specific parameters
                "temperature": temperature,
                "exaggeration": exaggeration
            }
            
            logger.info(f"🎵 Synthesizing: voice={voice}, text_length={len(text)}")
            
            response = await self.client.post(
                f"{self.base_url}/v1/audio/speech",
                json=payload,
                headers=self._get_headers(),
                timeout=30.0
            )
            
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Chatterbox API error: {response.status_code} - {error_text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Chatterbox API error: {error_text}"
                )
            
            audio_data = response.content
            logger.info(f"✅ Generated {len(audio_data)} bytes of audio")
            return audio_data
            
        except httpx.TimeoutException:
            logger.error("Chatterbox API timeout")
            raise HTTPException(status_code=504, detail="TTS service timeout")
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def clone_voice(
        self,
        audio_data: bytes,
        name: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """Clone a voice from reference audio"""
        if not ENABLE_VOICE_CLONING:
            raise HTTPException(status_code=403, detail="Voice cloning is disabled")
        
        try:
            self._ensure_client()
            
            files = {
                "file": (f"{name}.wav", BytesIO(audio_data), "audio/wav")
            }
            data = {
                "name": name,
                "description": description
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1/voices/clone",
                files=files,
                data=data,
                headers=self._get_headers(),
                timeout=60.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Voice cloning failed: {response.text}"
                )
            
            result = response.json()
            logger.info(f"✅ Voice cloned: {result.get('voice_id', name)}")
            return result
            
        except Exception as e:
            logger.error(f"Voice cloning error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

# Global client instance
chatterbox = ChatterboxClient()

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info(f"🚀 Starting June TTS Service")
    logger.info(f"📍 Chatterbox API: {CHATTERBOX_API_URL}")
    logger.info(f"🎤 Default voice: {DEFAULT_VOICE}")
    logger.info(f"🎭 Voice cloning: {'enabled' if ENABLE_VOICE_CLONING else 'disabled'}")
    
    # Test connection
    is_healthy = await chatterbox.health_check()
    if is_healthy:
        logger.info("✅ Chatterbox API is healthy")
    else:
        logger.warning("⚠️ Chatterbox API is not responding")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await chatterbox.close()

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    chatterbox_healthy = await chatterbox.health_check()
    
    return {
        "ok": True,
        "service": "june-tts",
        "version": "2.0.0",
        "timestamp": time.time(),
        "engine": "chatterbox",
        "chatterbox_api": {
            "url": CHATTERBOX_API_URL,
            "healthy": chatterbox_healthy
        },
        "features": {
            "voice_cloning": ENABLE_VOICE_CLONING,
            "streaming": True,
            "languages": 23
        }
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-tts",
        "version": "2.0.0",
        "engine": "chatterbox-tts-api",
        "docs": "/docs"
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    return {
        "voices": CHATTERBOX_VOICES,
        "default": DEFAULT_VOICE,
        "total": len(CHATTERBOX_VOICES)
    }

@app.post("/v1/tts")
async def synthesize_speech(
    text: str = Query(..., max_length=5000, description="Text to synthesize"),
    voice: str = Query(DEFAULT_VOICE, description="Voice ID"),
    speed: float = Query(DEFAULT_SPEED, ge=0.5, le=2.0),
    audio_encoding: str = Query("MP3", regex="^(MP3|WAV|OGG)$"),
    temperature: float = Query(DEFAULT_TEMPERATURE, ge=0.0, le=1.0),
    exaggeration: float = Query(DEFAULT_EXAGGERATION, ge=0.0, le=1.0),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Main TTS endpoint"""
    calling_service = service_auth_data.get("client_id", "unknown")
    start_time = time.time()
    
    try:
        logger.info(f"📝 TTS request from {calling_service}: {len(text)} chars")
        
        # Validate voice
        if voice not in CHATTERBOX_VOICES and voice != "default":
            logger.warning(f"Unknown voice '{voice}', using default")
            voice = DEFAULT_VOICE
        
        # Map audio encoding
        format_map = {
            "MP3": "mp3",
            "WAV": "wav",
            "OGG": "ogg"
        }
        response_format = format_map.get(audio_encoding.upper(), "mp3")
        
        # Generate audio
        audio_data = await chatterbox.synthesize(
            text=text,
            voice=voice,
            speed=speed,
            temperature=temperature,
            exaggeration=exaggeration,
            response_format=response_format
        )
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        # Determine media type
        media_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg"
        }
        media_type = media_types.get(response_format, "audio/mpeg")
        
        logger.info(f"✅ TTS complete: {len(audio_data)} bytes in {processing_time:.2f}s")
        
        return StreamingResponse(
            BytesIO(audio_data),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{response_format}",
                "X-Processing-Time": f"{processing_time:.3f}",
                "X-Voice": voice,
                "X-Engine": "chatterbox"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

@app.post("/v1/voice-clone")
async def clone_voice(
    file: UploadFile = File(..., description="Reference audio (WAV/MP3)"),
    name: str = Form(..., min_length=1, max_length=50),
    description: Optional[str] = Form(None, max_length=200),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning endpoint"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Validate file type
        if not file.content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail="File must be audio format")
        
        # Read audio data
        audio_data = await file.read()
        if len(audio_data) > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")
        
        logger.info(f"🎤 Voice clone request from {calling_service}: {name}")
        
        # Clone voice
        result = await chatterbox.clone_voice(
            audio_data=audio_data,
            name=name,
            description=description or f"Cloned by {calling_service}"
        )
        
        return {
            "success": True,
            "voice_id": result.get("voice_id", name),
            "name": name,
            "description": description,
            "message": "Voice cloned successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice cloning error: {e}")
        raise HTTPException(status_code=500, detail="Voice cloning failed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    workers = int(os.getenv("WORKERS", "1"))
    
    logger.info(f"🚀 Starting server on port {port} with {workers} workers")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )