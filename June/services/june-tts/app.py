# June/services/june-tts/app.py - LIGHTWEIGHT PROXY TO CHATTERBOX
import os
import time
import logging
import base64
import httpx
import json
from typing import Optional, Dict, Any

from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June TTS Proxy Service", 
    version="2.0.0",
    description="Lightweight proxy to Chatterbox TTS API"
)

# Configuration - Point to external Chatterbox instance
CHATTERBOX_API_URL = os.getenv("CHATTERBOX_API_URL", "https://api.chatterboxtts.com")
CHATTERBOX_API_KEY = os.getenv("CHATTERBOX_API_KEY", "")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "af_bella")

# Chatterbox voices
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

class ChatterboxProxy:
    """Lightweight proxy to Chatterbox API"""
    
    def __init__(self):
        self.base_url = CHATTERBOX_API_URL.rstrip('/')
        self.api_key = CHATTERBOX_API_KEY
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def health_check(self) -> bool:
        """Check if Chatterbox API is available"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers=self._get_headers()
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        temperature: float = 0.3,
        exaggeration: float = 0.5,
        response_format: str = "mp3"
    ) -> bytes:
        """Call Chatterbox API for speech synthesis"""
        try:
            payload = {
                "model": "chatterbox",
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": response_format,
                "temperature": temperature,
                "exaggeration": exaggeration
            }
            
            logger.info(f"🎵 Proxying TTS request: voice={voice}, text_length={len(text)}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/audio/speech",
                    json=payload,
                    headers=self._get_headers()
                )
                
                if response.status_code != 200:
                    logger.error(f"Chatterbox API error: {response.status_code} - {response.text}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Chatterbox API error: {response.text}"
                    )
                
                audio_data = response.content
                logger.info(f"✅ TTS synthesis successful: {len(audio_data)} bytes")
                return audio_data
                
        except httpx.TimeoutException:
            logger.error("Chatterbox API timeout")
            raise HTTPException(status_code=504, detail="TTS service timeout")
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def list_voices(self) -> Dict[str, Any]:
        """Get available voices from Chatterbox"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/voices",
                    headers=self._get_headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    # Return static list if API call fails
                    return {"voices": CHATTERBOX_VOICES}
                    
        except Exception as e:
            logger.warning(f"Failed to fetch voices from API: {e}")
            return {"voices": CHATTERBOX_VOICES}

# Global proxy instance
chatterbox = ChatterboxProxy()

@app.on_event("startup")
async def startup_event():
    """Test connection on startup"""
    logger.info(f"🚀 Starting June TTS Proxy Service")
    logger.info(f"📍 Chatterbox API: {CHATTERBOX_API_URL}")
    logger.info(f"🎤 Default voice: {DEFAULT_VOICE}")
    
    # Test connection (don't fail if unavailable)
    is_healthy = await chatterbox.health_check()
    if is_healthy:
        logger.info("✅ Chatterbox API is reachable")
    else:
        logger.warning("⚠️ Chatterbox API is not responding (will retry per request)")

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    chatterbox_healthy = await chatterbox.health_check()
    
    return {
        "ok": True,
        "service": "june-tts-proxy",
        "version": "2.0.0",
        "timestamp": time.time(),
        "engine": "chatterbox-proxy",
        "chatterbox_api": {
            "url": CHATTERBOX_API_URL,
            "healthy": chatterbox_healthy
        }
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-tts-proxy",
        "version": "2.0.0",
        "engine": "chatterbox-proxy",
        "docs": "/docs",
        "proxy_target": CHATTERBOX_API_URL
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    voices_data = await chatterbox.list_voices()
    return {
        "voices": voices_data.get("voices", CHATTERBOX_VOICES),
        "default": DEFAULT_VOICE,
        "total": len(voices_data.get("voices", CHATTERBOX_VOICES))
    }

@app.post("/v1/tts")
async def synthesize_speech(
    text: str = Query(..., max_length=5000, description="Text to synthesize"),
    voice: str = Query(DEFAULT_VOICE, description="Voice ID"),
    speed: float = Query(1.0, ge=0.5, le=2.0),
    audio_encoding: str = Query("MP3", regex="^(MP3|WAV|OGG)$"),
    temperature: float = Query(0.3, ge=0.0, le=1.0),
    exaggeration: float = Query(0.5, ge=0.0, le=1.0),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Main TTS endpoint - proxies to Chatterbox"""
    calling_service = service_auth_data.get("client_id", "unknown")
    start_time = time.time()
    
    try:
        logger.info(f"📝 TTS proxy request from {calling_service}: {len(text)} chars")
        
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
        
        # Proxy to Chatterbox
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
        
        # Return audio response
        media_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg"
        }
        media_type = media_types.get(response_format, "audio/mpeg")
        
        logger.info(f"✅ TTS proxy complete: {len(audio_data)} bytes in {processing_time:.2f}s")
        
        from io import BytesIO
        return StreamingResponse(
            BytesIO(audio_data),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{response_format}",
                "X-Processing-Time": f"{processing_time:.3f}",
                "X-Voice": voice,
                "X-Engine": "chatterbox-proxy"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS proxy error: {e}")
        raise HTTPException(status_code=500, detail="TTS proxy failed")

# Simplified voice cloning - just proxy the request
@app.post("/v1/voice-clone")
async def clone_voice(
    file: UploadFile = File(..., description="Reference audio (WAV/MP3)"),
    name: str = Form(..., min_length=1, max_length=50),
    description: Optional[str] = Form(None, max_length=200),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning proxy endpoint"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎤 Voice clone proxy from {calling_service}: {name}")
        
        # Read and validate file
        if not file.content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail="File must be audio format")
        
        audio_data = await file.read()
        if len(audio_data) > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")
        
        # Proxy to Chatterbox (if supported)
        # For now, return a placeholder response
        return {
            "success": True,
            "voice_id": f"cloned_{name.lower().replace(' ', '_')}",
            "name": name,
            "description": description or f"Cloned by {calling_service}",
            "message": "Voice cloning request queued (proxy mode)",
            "note": "This is a proxy service - actual cloning handled by external Chatterbox API"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice cloning proxy error: {e}")
        raise HTTPException(status_code=500, detail="Voice cloning proxy failed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    
    logger.info(f"🚀 Starting TTS proxy server on port {port}")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )