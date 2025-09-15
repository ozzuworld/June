import os
import io
import time
import logging
import asyncio
import tempfile
import base64
import hashlib
from typing import Optional, Dict, Any, List
from pathlib import Path
import json

import torch
import torchaudio
import soundfile as sf
import numpy as np
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import aiofiles

# Use Coqui TTS instead of chatterbox-tts (more stable)
try:
    from TTS.api import TTS
    TTS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"TTS not available: {e}")
    TTS_AVAILABLE = False

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="June Chatterbox TTS Service", version="1.0.0")

# =============================================================================
# CONFIGURATION
# =============================================================================

class TTSConfig:
    def __init__(self):
        self.device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        self.models_path = Path(os.getenv("MODELS_PATH", "/app/models"))
        self.voices_path = Path(os.getenv("VOICES_PATH", "/app/voices"))
        self.cache_path = Path(os.getenv("CACHE_PATH", "/app/cache"))
        self.default_language = os.getenv("DEFAULT_LANGUAGE", "en")
        self.enable_multilingual = os.getenv("ENABLE_MULTILINGUAL", "true").lower() == "true"
        self.max_text_length = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
        self.enable_voice_cloning = os.getenv("ENABLE_VOICE_CLONING", "true").lower() == "true"
        self.enable_emotion_control = os.getenv("ENABLE_EMOTION_CONTROL", "true").lower() == "true"
        
        # Create directories
        self.models_path.mkdir(parents=True, exist_ok=True)
        self.voices_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)

config = TTSConfig()

# =============================================================================
# VOICE PROFILES AND MANAGEMENT
# =============================================================================

class VoiceProfile:
    def __init__(self, name: str, description: str, model_name: str = None, 
                 language: str = "en", emotion_preset: Dict[str, float] = None):
        self.name = name
        self.description = description
        self.model_name = model_name or "tts_models/en/ljspeech/tacotron2-DDC"
        self.language = language
        self.emotion_preset = emotion_preset or {
            "speed": 1.0,
            "pitch": 1.0,
            "energy": 1.0
        }

# Predefined voice profiles using Coqui TTS models
VOICE_PROFILES = {
    "assistant_female": VoiceProfile(
        name="Assistant Female",
        description="Professional female assistant voice",
        model_name="tts_models/en/ljspeech/tacotron2-DDC",
        language="en",
        emotion_preset={"speed": 1.0, "pitch": 1.0, "energy": 0.8}
    ),
    "assistant_male": VoiceProfile(
        name="Assistant Male", 
        description="Professional male assistant voice",
        model_name="tts_models/en/ljspeech/glow-tts",
        language="en",
        emotion_preset={"speed": 1.0, "pitch": 0.9, "energy": 0.8}
    ),
    "narrator_warm": VoiceProfile(
        name="Warm Narrator",
        description="Warm, storytelling voice",
        model_name="tts_models/en/ljspeech/speedy-speech",
        language="en", 
        emotion_preset={"speed": 0.9, "pitch": 1.1, "energy": 1.1}
    ),
    "conversation_friendly": VoiceProfile(
        name="Friendly Conversational",
        description="Casual, friendly conversation voice",
        model_name="tts_models/en/ljspeech/tacotron2-DDC",
        language="en",
        emotion_preset={"speed": 1.1, "pitch": 1.0, "energy": 1.0}
    )
}

# =============================================================================
# MODELS AND INITIALIZATION
# =============================================================================

class TTSService:
    def __init__(self):
        self.models = {}
        self.is_initialized = False
        self.supported_languages = ["en"]
        
    async def initialize(self):
        """Initialize TTS models"""
        if not TTS_AVAILABLE:
            logger.error("TTS library not available")
            return False
            
        try:
            logger.info(f"Initializing TTS on device: {config.device}")
            
            # Initialize default English model
            default_model = "tts_models/en/ljspeech/tacotron2-DDC"
            logger.info(f"Loading default model: {default_model}")
            
            self.models["default"] = TTS(
                model_name=default_model, 
                progress_bar=False, 
                gpu=(config.device == "cuda")
            )
            
            logger.info("✅ Default TTS model loaded successfully")
            
            # Initialize multilingual model if enabled
            if config.enable_multilingual:
                try:
                    multilingual_model = "tts_models/multilingual/multi-dataset/xtts_v2"
                    logger.info(f"Loading multilingual model: {multilingual_model}")
                    
                    self.models["multilingual"] = TTS(
                        model_name=multilingual_model,
                        progress_bar=False,
                        gpu=(config.device == "cuda")
                    )
                    
                    self.supported_languages = [
                        "en", "es", "fr", "de", "it", "pt", "pl", "tr", 
                        "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko"
                    ]
                    logger.info("✅ Multilingual TTS model loaded successfully")
                except Exception as e:
                    logger.warning(f"Failed to load multilingual model: {e}")
            
            self.is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize TTS: {e}")
            return False
    
    def get_model_for_language(self, language: str = "en"):
        """Get the appropriate model for the given language"""
        if language == "en" or not config.enable_multilingual:
            return self.models.get("default")
        elif language in self.supported_languages and "multilingual" in self.models:
            return self.models.get("multilingual")
        else:
            logger.warning(f"Language {language} not supported, falling back to English")
            return self.models.get("default")
    
    async def synthesize(self, text: str, voice_profile: str = "assistant_female",
                        language: str = "en", speed_factor: float = 1.0,
                        pitch_factor: float = 1.0, energy_factor: float = 1.0) -> Optional[np.ndarray]:
        """Synthesize speech using TTS"""
        
        if not self.is_initialized:
            logger.error("TTS service not initialized")
            return None
            
        try:
            # Get model and voice profile
            model = self.get_model_for_language(language)
            if not model:
                logger.error(f"No model available for language: {language}")
                return None
            
            profile = VOICE_PROFILES.get(voice_profile, VOICE_PROFILES["assistant_female"])
            
            logger.info(f"Generating speech: '{text[:50]}...' with {profile.name}")
            
            # Generate audio
            if language != "en" and "multilingual" in self.models and model == self.models["multilingual"]:
                # Use multilingual model with language specification
                wav = model.tts(text=text, language=language)
            else:
                # Use default English model
                wav = model.tts(text=text)
            
            # Convert to numpy array if needed
            if torch.is_tensor(wav):
                wav = wav.cpu().numpy()
            elif isinstance(wav, list):
                wav = np.array(wav)
            
            # Apply speed factor if needed
            if speed_factor != 1.0 and speed_factor > 0:
                # Simple time stretching
                new_length = int(len(wav) / speed_factor)
                if new_length > 0:
                    import scipy.signal
                    wav = scipy.signal.resample(wav, new_length)
            
            logger.info(f"✅ Speech generated successfully: {len(wav)} samples")
            return wav
            
        except Exception as e:
            logger.error(f"Speech synthesis failed: {e}")
            return None

# Global service instance
tts_service = TTSService()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    voice_profile: str = Field("assistant_female", description="Voice profile to use")
    language: str = Field("en", description="Language code (en, es, fr, etc.)")
    speed_factor: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    pitch_factor: float = Field(1.0, ge=0.5, le=2.0, description="Pitch adjustment")
    energy_factor: float = Field(1.0, ge=0.5, le=2.0, description="Energy/volume adjustment")
    audio_format: str = Field("wav", description="Output format: wav, mp3, or ogg")

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def convert_audio_format(audio_data: np.ndarray, sample_rate: int, 
                        target_format: str) -> bytes:
    """Convert audio to target format"""
    
    try:
        # Ensure audio is in correct format
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)
        
        if target_format.lower() == "wav":
            # Convert to WAV
            buffer = io.BytesIO()
            sf.write(buffer, audio_data, sample_rate, format='WAV')
            return buffer.getvalue()
            
        elif target_format.lower() == "mp3":
            # Convert to MP3 via temporary WAV
            with tempfile.NamedTemporaryFile(suffix=".wav") as wav_temp:
                sf.write(wav_temp.name, audio_data, sample_rate)
                
                with tempfile.NamedTemporaryFile(suffix=".mp3") as mp3_temp:
                    # Use ffmpeg to convert
                    import subprocess
                    cmd = [
                        "ffmpeg", "-i", wav_temp.name,
                        "-acodec", "mp3", "-ab", "128k", "-y", mp3_temp.name
                    ]
                    subprocess.run(cmd, capture_output=True, check=True)
                    
                    with open(mp3_temp.name, "rb") as f:
                        return f.read()
        
        else:
            # Default to WAV
            buffer = io.BytesIO()
            sf.write(buffer, audio_data, sample_rate, format='WAV')
            return buffer.getvalue()
            
    except Exception as e:
        logger.error(f"Audio conversion failed: {e}")
        # Fallback to WAV
        buffer = io.BytesIO()
        sf.write(buffer, audio_data, sample_rate, format='WAV')
        return buffer.getvalue()

def determine_media_type(audio_format: str) -> str:
    """Determine media type for response"""
    format_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg", 
        "ogg": "audio/ogg"
    }
    return format_map.get(audio_format.lower(), "audio/wav")

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers - FIXED for proper startup handling"""
    try:
        # Calculate startup time
        startup_time = time.time() - (getattr(app.state, 'startup_time', time.time()))
        
        health_data = {
            "ok": True,
            "service": "june-chatterbox-tts",
            "timestamp": time.time(),
            "status": "healthy",
            "tts_available": TTS_AVAILABLE,
            "device": config.device,
            "multilingual_enabled": config.enable_multilingual,
            "supported_languages": tts_service.supported_languages,
            "voice_profiles": list(VOICE_PROFILES.keys()),
            "engine": "coqui-tts",
            "startup_time": startup_time
        }
        
        # Check if TTS service is properly initialized
        if not tts_service.is_initialized:
            # During startup period (first 5 minutes), return initializing status
            if startup_time < 300:  # 5 minutes grace period
                health_data.update({
                    "status": "initializing",
                    "message": "TTS models are loading, please wait...",
                    "estimated_ready_in": max(0, 300 - startup_time)
                })
                return health_data  # Return 200 but with initializing status
            else:
                health_data.update({
                    "status": "unhealthy",
                    "message": "TTS initialization failed or timed out"
                })
                return health_data
        
        # Service is ready
        health_data.update({
            "models_loaded": True,
            "ready_for_synthesis": True,
            "features": {
                "emotion_control": config.enable_emotion_control,
                "voice_cloning": config.enable_voice_cloning,
                "multilingual": config.enable_multilingual
            }
        })
        
        return health_data
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "ok": False,
            "service": "june-chatterbox-tts",
            "timestamp": time.time(),
            "status": "unhealthy",
            "error": str(e)
        }

# ALSO ADD this to your app startup to track startup time
@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    # Track startup time for health checks
    app.state.startup_time = time.time()
    
    logger.info("Starting June TTS Service...")
    
    success = await tts_service.initialize()
    if success:
        logger.info("✅ TTS service initialized successfully")
    else:
        logger.error("❌ Failed to initialize TTS service")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-chatterbox-tts",
        "status": "running",
        "tts_available": TTS_AVAILABLE,
        "engine": "coqui-tts",
        "features": {
            "multilingual": config.enable_multilingual,
            "voice_profiles": True,
            "speed_control": True,
            "pitch_control": True
        },
        "supported_languages": tts_service.supported_languages,
        "voice_profiles": {name: profile.description for name, profile in VOICE_PROFILES.items()}
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voice profiles"""
    return {
        "voices": {
            name: {
                "name": profile.name,
                "description": profile.description,
                "language": profile.language,
                "model": profile.model_name,
                "emotion_preset": profile.emotion_preset
            }
            for name, profile in VOICE_PROFILES.items()
        },
        "default": "assistant_female",
        "engine": "coqui-tts",
        "features": {
            "multilingual": True,
            "speed_control": True,
            "pitch_control": True,
            "energy_control": True
        }
    }

@app.get("/v1/languages")
async def list_languages():
    """List supported languages"""
    return {
        "languages": tts_service.supported_languages,
        "multilingual_enabled": config.enable_multilingual,
        "default_language": config.default_language,
        "engine": "coqui-tts"
    }

# Service-to-Service TTS Endpoint (Compatible with existing orchestrator)
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("assistant_female", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_encoding: str = Query("MP3", description="Audio format: MP3, WAV, or OGG"),
    language: str = Query("en", description="Language code"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    TTS endpoint for service-to-service communication
    Compatible with existing orchestrator integration
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Validate input
        if len(text) > config.max_text_length:
            raise HTTPException(status_code=400, detail=f"Text too long (max {config.max_text_length} characters)")
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:50]}...' ({len(text)} chars)")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        # Map voice parameter to voice profile
        voice_profile = voice if voice in VOICE_PROFILES else "assistant_female"
        
        # Generate speech
        audio_data = await tts_service.synthesize(
            text=text,
            voice_profile=voice_profile,
            language=language,
            speed_factor=speed
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Default sample rate for Coqui TTS
        sample_rate = 22050
        
        # Convert to requested format
        audio_bytes = convert_audio_format(audio_data, sample_rate, audio_encoding)
        
        # Determine media type
        media_type = determine_media_type(audio_encoding)
        
        logger.info(f"✅ TTS synthesis successful: {len(audio_bytes)} bytes generated")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{audio_encoding.lower()}",
                "X-Processed-By": "june-chatterbox-tts",
                "X-Caller-Service": calling_service,
                "X-TTS-Engine": "coqui-tts",
                "X-Voice-Profile": voice_profile,
                "X-Audio-Length": str(len(audio_data))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Advanced TTS endpoint with full feature set
@app.post("/v1/tts/advanced")
async def synthesize_speech_advanced(
    request: TTSRequest,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Advanced TTS endpoint with full TTS features"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎭 Advanced TTS request from {calling_service}")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        # Generate speech
        audio_data = await tts_service.synthesize(
            text=request.text,
            voice_profile=request.voice_profile,
            language=request.language,
            speed_factor=request.speed_factor,
            pitch_factor=request.pitch_factor,
            energy_factor=request.energy_factor
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Default sample rate
        sample_rate = 22050
        
        # Convert to requested format
        audio_bytes = convert_audio_format(audio_data, sample_rate, request.audio_format)
        media_type = determine_media_type(request.audio_format)
        
        logger.info(f"✅ Advanced TTS synthesis successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "X-TTS-Engine": "coqui-tts",
                "X-Voice-Profile": request.voice_profile,
                "X-Language": request.language,
                "X-Caller-Service": calling_service
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Advanced TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))