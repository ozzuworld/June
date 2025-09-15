# June/services/june-kokoro-tts/app.py - SIMPLIFIED VERSION
import os
import io
import time
import logging
import asyncio
from typing import Optional, Dict, Any
import tempfile
import subprocess
from pathlib import Path

from fastapi import FastAPI, Query, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse

# Google Cloud TTS (reliable and proven)
try:
    from google.cloud import texttospeech
    from google.oauth2 import service_account
    import json
    tts_client = None
    
    def build_tts_client():
        # Try different credential sources
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            return texttospeech.TextToSpeechClient()
        
        sa_path = os.getenv("GCP_SA_PATH")
        if sa_path and os.path.exists(sa_path):
            creds = service_account.Credentials.from_service_account_file(sa_path)
            return texttospeech.TextToSpeechClient(credentials=creds)
        
        sa_json = os.getenv("GCP_SA_JSON")
        if sa_json:
            info = json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(info)
            return texttospeech.TextToSpeechClient(credentials=creds)
        
        # Fall back to default
        return texttospeech.TextToSpeechClient()
    
    tts_client = build_tts_client()
    logger = logging.getLogger(__name__)
    logger.info("✅ Google Cloud TTS client initialized")
    
except Exception as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ Google Cloud TTS not available: {e}")
    tts_client = None

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="June TTS Service", version="1.0.0")

# Voice mapping for compatibility
AVAILABLE_VOICES = {
    "af_bella": {
        "name": "en-US-Journey-F",
        "language_code": "en-US",
        "description": "American Female - Bella"
    },
    "af_nicole": {
        "name": "en-US-Studio-O", 
        "language_code": "en-US",
        "description": "American Female - Nicole"
    },
    "af_sarah": {
        "name": "en-US-Wavenet-C",
        "language_code": "en-US", 
        "description": "American Female - Sarah"
    },
    "af_sky": {
        "name": "en-US-Wavenet-E",
        "language_code": "en-US",
        "description": "American Female - Sky"
    },
    "am_adam": {
        "name": "en-US-Wavenet-A",
        "language_code": "en-US",
        "description": "American Male - Adam"
    },
    "am_michael": {
        "name": "en-US-Wavenet-B",
        "language_code": "en-US",
        "description": "American Male - Michael"
    }
}

async def synthesize_with_google_tts(
    text: str,
    voice: str = "af_bella",
    speed: float = 1.0,
    audio_encoding: str = "MP3"
) -> Optional[bytes]:
    """Synthesize speech using Google Cloud TTS"""
    try:
        if not tts_client:
            logger.error("Google Cloud TTS client not available")
            return None
        
        # Get voice configuration
        voice_config = AVAILABLE_VOICES.get(voice, AVAILABLE_VOICES["af_bella"])
        
        # Create synthesis input
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # Configure voice
        voice_params = texttospeech.VoiceSelectionParams(
            language_code=voice_config["language_code"],
            name=voice_config["name"]
        )
        
        # Configure audio
        encoding_map = {
            "MP3": texttospeech.AudioEncoding.MP3,
            "WAV": texttospeech.AudioEncoding.LINEAR16,
            "OGG": texttospeech.AudioEncoding.OGG_OPUS
        }
        
        audio_encoding_enum = encoding_map.get(audio_encoding.upper(), texttospeech.AudioEncoding.MP3)
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=audio_encoding_enum,
            speaking_rate=speed
        )
        
        # Synthesize speech
        response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config
        )
        
        logger.info(f"✅ Google TTS synthesis successful: {len(response.audio_content)} bytes")
        return response.audio_content
        
    except Exception as e:
        logger.error(f"❌ Google TTS synthesis failed: {e}")
        return None

async def synthesize_with_espeak_fallback(
    text: str,
    voice: str = "af_bella", 
    speed: float = 1.0,
    audio_encoding: str = "MP3"
) -> Optional[bytes]:
    """Fallback synthesis using eSpeak-NG"""
    try:
        logger.info("🔧 Using eSpeak-NG fallback synthesis")
        
        # Use eSpeak-NG with better voice settings
        espeak_cmd = [
            "espeak-ng",
            "-v", "en+f3",  # Female voice variant
            "-s", str(int(150 * speed)),  # Speed (words per minute)
            "-a", "100",  # Amplitude
            "-g", "5",    # Gap between words
            "--stdout",
            text
        ]
        
        # Run eSpeak-NG
        result = subprocess.run(
            espeak_cmd,
            capture_output=True,
            check=True
        )
        
        audio_data = result.stdout
        
        if audio_encoding.upper() == "MP3":
            # Convert WAV to MP3 using ffmpeg
            return await convert_wav_to_mp3(audio_data)
        
        return audio_data
        
    except Exception as e:
        logger.error(f"❌ eSpeak fallback synthesis failed: {e}")
        return None

async def convert_wav_to_mp3(wav_data: bytes) -> bytes:
    """Convert WAV data to MP3"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:
            with tempfile.NamedTemporaryFile(suffix=".mp3") as mp3_file:
                wav_file.write(wav_data)
                wav_file.flush()
                
                # Use ffmpeg to convert
                cmd = [
                    "ffmpeg", "-i", wav_file.name,
                    "-acodec", "mp3", "-ab", "128k",
                    "-y", mp3_file.name
                ]
                
                subprocess.run(cmd, capture_output=True, check=True)
                
                mp3_file.seek(0)
                return mp3_file.read()
                
    except Exception as e:
        logger.error(f"❌ WAV to MP3 conversion failed: {e}")
        return wav_data  # Return original if conversion fails

# Health check endpoint
@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    return {
        "ok": True,
        "service": "june-tts",
        "timestamp": time.time(),
        "status": "healthy",
        "tts_engine": "google-cloud" if tts_client else "espeak-fallback",
        "voices_available": len(AVAILABLE_VOICES)
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-tts",
        "status": "running",
        "engine": "google-cloud-tts" if tts_client else "espeak-fallback",
        "voices": list(AVAILABLE_VOICES.keys())
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    return {
        "voices": AVAILABLE_VOICES,
        "default": "af_bella",
        "engine": "google-cloud" if tts_client else "espeak"
    }

# Service-to-Service TTS Endpoint
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("af_bella", description="Voice to use"),
    speed: float = Query(1.0, description="Speech speed (0.5-2.0)"),
    audio_encoding: str = Query("MP3", description="Audio format: MP3, WAV, or OGG"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    TTS endpoint for service-to-service communication
    Protected by service authentication
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Validate input
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        if speed < 0.5 or speed > 2.0:
            raise HTTPException(status_code=400, detail="Speed must be between 0.5 and 2.0")
        
        if voice not in AVAILABLE_VOICES:
            logger.warning(f"Voice '{voice}' not available, using default")
            voice = "