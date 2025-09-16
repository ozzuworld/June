# June/services/june-tts/app.py - REAL TTS IMPLEMENTATION
import os
import time
import logging
import tempfile
import base64
from typing import Optional
import io

from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="June TTS Service", version="1.0.0")

# Try to use Google Cloud TTS (best option)
try:
    from google.cloud import texttospeech
    tts_client = texttospeech.TextToSpeechClient()
    GOOGLE_TTS_AVAILABLE = True
    logger.info("✅ Google Cloud Text-to-Speech initialized")
except Exception as e:
    GOOGLE_TTS_AVAILABLE = False
    logger.warning(f"⚠️ Google Cloud TTS not available: {e}")

# Fallback: Try gTTS (Google Text-to-Speech unofficial)
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
    logger.info("✅ gTTS initialized as fallback")
except ImportError:
    GTTS_AVAILABLE = False
    logger.warning("⚠️ gTTS not available")

# Configuration
WRAPPER_PORT = int(os.getenv("PORT", "8080"))

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    language: str = Field("en", description="Language code")
    voice: str = Field("default", description="Voice profile")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed")

def synthesize_with_google_tts(text: str, language: str = "en-US", voice_name: str = None) -> bytes:
    """Use Google Cloud Text-to-Speech"""
    try:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # Configure voice
        if not voice_name:
            voice_name = "en-US-Journey-F" if "en" in language else f"{language}-Standard-A"
        
        voice = texttospeech.VoiceSelectionParams(
            language_code=language[:5] if len(language) > 5 else language,
            name=voice_name,
        )
        
        # Configure audio
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0,
        )
        
        # Generate speech
        response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        logger.info(f"✅ Google TTS synthesis successful: {len(response.audio_content)} bytes")
        return response.audio_content
        
    except Exception as e:
        logger.error(f"❌ Google TTS failed: {e}")
        raise

def synthesize_with_gtts(text: str, language: str = "en") -> bytes:
    """Use gTTS as fallback"""
    try:
        # Map language codes
        lang_map = {
            "en-US": "en",
            "es-ES": "es", 
            "fr-FR": "fr",
            "de-DE": "de",
            "it-IT": "it",
            "pt-BR": "pt",
            "zh-CN": "zh",
            "ja-JP": "ja",
            "ko-KR": "ko",
        }
        
        gtts_lang = lang_map.get(language, language[:2] if len(language) > 2 else language)
        
        # Generate speech
        tts = gTTS(text=text, lang=gtts_lang, slow=False)
        
        # Save to bytes
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        audio_bytes = audio_buffer.read()
        
        logger.info(f"✅ gTTS synthesis successful: {len(audio_bytes)} bytes")
        return audio_bytes
        
    except Exception as e:
        logger.error(f"❌ gTTS failed: {e}")
        raise

@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    return {
        "ok": True,
        "service": "june-tts",
        "timestamp": time.time(),
        "status": "healthy",
        "engines": {
            "google_cloud_tts": GOOGLE_TTS_AVAILABLE,
            "gtts": GTTS_AVAILABLE,
        }
    }

@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("default", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_encoding: str = Query("MP3", description="Audio format"),
    language: str = Query("en-US", description="Language code"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """TTS endpoint for service-to-service communication"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:50]}...'")
        
        audio_data = None
        
        # Try Google Cloud TTS first
        if GOOGLE_TTS_AVAILABLE:
            try:
                audio_data = synthesize_with_google_tts(text, language, voice if voice != "default" else None)
            except Exception as e:
                logger.warning(f"Google TTS failed, trying fallback: {e}")
        
        # Fallback to gTTS
        if not audio_data and GTTS_AVAILABLE:
            try:
                audio_data = synthesize_with_gtts(text, language)
            except Exception as e:
                logger.error(f"gTTS also failed: {e}")
        
        # Last resort: return error
        if not audio_data:
            logger.error("❌ No TTS engine available")
            raise HTTPException(status_code=503, detail="No TTS engine available")
        
        logger.info(f"✅ TTS synthesis successful: {len(audio_data)} bytes")
        
        return StreamingResponse(
            iter([audio_data]),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"attachment; filename=speech.mp3",
                "X-TTS-Engine": "google-tts" if GOOGLE_TTS_AVAILABLE else "gtts",
                "X-Caller-Service": calling_service,
                "X-Text-Length": str(len(text)),
                "X-Audio-Length": str(len(audio_data))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting June TTS Service on port {WRAPPER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=WRAPPER_PORT, workers=1)