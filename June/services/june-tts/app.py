# File: June/services/june-tts/app.py
# Complete Chatterbox TTS Service Implementation

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

# Import Chatterbox TTS instead of Coqui
try:
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    CHATTERBOX_AVAILABLE = True
    logging.info("✅ Chatterbox TTS library imported successfully")
except ImportError as e:
    logging.warning(f"❌ Chatterbox TTS not available: {e}")
    CHATTERBOX_AVAILABLE = False

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
        
        logger.info(f"TTS Config initialized - Device: {self.device}, Multilingual: {self.enable_multilingual}")

config = TTSConfig()

# =============================================================================
# VOICE PROFILES AND MANAGEMENT
# =============================================================================

class VoiceProfile:
    def __init__(self, name: str, description: str, language: str = "en", 
                 emotion_preset: Dict[str, float] = None):
        self.name = name
        self.description = description
        self.language = language
        self.emotion_preset = emotion_preset or {
            "cfg_weight": 0.5,
            "exaggeration": 0.5,
            "temperature": 1.0
        }

# Predefined voice profiles for Chatterbox TTS
VOICE_PROFILES = {
    "assistant_female": VoiceProfile(
        name="Assistant Female",
        description="Professional female assistant voice with natural delivery",
        language="en",
        emotion_preset={"cfg_weight": 0.5, "exaggeration": 0.3, "temperature": 0.8}
    ),
    "assistant_male": VoiceProfile(
        name="Assistant Male", 
        description="Professional male assistant voice with clear articulation",
        language="en",
        emotion_preset={"cfg_weight": 0.5, "exaggeration": 0.3, "temperature": 0.8}
    ),
    "narrator_warm": VoiceProfile(
        name="Warm Narrator",
        description="Expressive storytelling voice with emotional depth",
        language="en", 
        emotion_preset={"cfg_weight": 0.4, "exaggeration": 0.7, "temperature": 1.1}
    ),
    "conversation_friendly": VoiceProfile(
        name="Friendly Conversational",
        description="Casual, energetic conversation voice",
        language="en",
        emotion_preset={"cfg_weight": 0.6, "exaggeration": 0.6, "temperature": 1.0}
    ),
    "audiobook_calm": VoiceProfile(
        name="Calm Audiobook Narrator",
        description="Steady, soothing voice perfect for long-form content",
        language="en",
        emotion_preset={"cfg_weight": 0.3, "exaggeration": 0.2, "temperature": 0.9}
    )
}

# =============================================================================
# CHATTERBOX TTS SERVICE
# =============================================================================

class ChatterboxTTSService:
    def __init__(self):
        self.models = {}
        self.is_initialized = False
        self.supported_languages = ["en"]
        
    async def initialize(self):
        """Initialize Chatterbox TTS models"""
        if not CHATTERBOX_AVAILABLE:
            logger.error("❌ Chatterbox TTS library not available")
            return False
            
        try:
            logger.info(f"🎤 Initializing Chatterbox TTS on device: {config.device}")
            
            # Initialize English model first
            logger.info("📥 Loading Chatterbox English model...")
            self.models["english"] = ChatterboxTTS.from_pretrained(device=config.device)
            logger.info("✅ Chatterbox English model loaded successfully")
            
            # Initialize multilingual model if enabled
            if config.enable_multilingual:
                try:
                    logger.info("📥 Loading Chatterbox Multilingual model...")
                    self.models["multilingual"] = ChatterboxMultilingualTTS.from_pretrained(device=config.device)
                    
                    # Chatterbox supports 23 languages
                    self.supported_languages = [
                        "en", "es", "fr", "de", "it", "pt", "pl", "tr", 
                        "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko",
                        "hi", "th", "vi", "uk", "sw", "da", "no"
                    ]
                    logger.info("✅ Chatterbox Multilingual model loaded successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load multilingual model: {e}")
            
            self.is_initialized = True
            logger.info("🎉 Chatterbox TTS service fully initialized!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Chatterbox TTS: {e}")
            return False
    
    def get_model_for_language(self, language: str = "en"):
        """Get the appropriate model for the given language"""
        if language == "en" or not config.enable_multilingual:
            return self.models.get("english")
        elif language in self.supported_languages and "multilingual" in self.models:
            return self.models.get("multilingual")
        else:
            logger.warning(f"Language {language} not supported, falling back to English")
            return self.models.get("english")
    
    async def synthesize(self, text: str, voice_profile: str = "assistant_female",
                        language: str = "en", reference_audio: Optional[bytes] = None,
                        cfg_weight: float = None, exaggeration: float = None,
                        temperature: float = None) -> Optional[np.ndarray]:
        """Synthesize speech using Chatterbox TTS"""
        
        if not self.is_initialized:
            logger.error("❌ Chatterbox TTS service not initialized")
            return None
            
        try:
            # Get model and voice profile
            model = self.get_model_for_language(language)
            if not model:
                logger.error(f"❌ No model available for language: {language}")
                return None
            
            profile = VOICE_PROFILES.get(voice_profile, VOICE_PROFILES["assistant_female"])
            
            # Use profile defaults if parameters not specified
            cfg_weight = cfg_weight if cfg_weight is not None else profile.emotion_preset.get("cfg_weight", 0.5)
            exaggeration = exaggeration if exaggeration is not None else profile.emotion_preset.get("exaggeration", 0.5)
            temperature = temperature if temperature is not None else profile.emotion_preset.get("temperature", 1.0)
            
            logger.info(f"🎵 Generating speech: '{text[:50]}...' with {profile.name}")
            logger.info(f"⚙️ Parameters: cfg_weight={cfg_weight}, exaggeration={exaggeration}, temperature={temperature}")
            
            # Generate audio with Chatterbox
            if reference_audio and config.enable_voice_cloning:
                # Voice cloning with reference audio
                logger.info("🎤 Using voice cloning with reference audio")
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
                    ref_file.write(reference_audio)
                    ref_file.flush()
                    
                    try:
                        # Generate with voice cloning
                        if language != "en" and model == self.models.get("multilingual"):
                            wav = model.generate(
                                text=text,
                                reference_path=ref_file.name,
                                language=language,
                                cfg_weight=cfg_weight,
                                exaggeration=exaggeration,
                                temperature=temperature
                            )
                        else:
                            wav = model.generate(
                                text=text,
                                reference_path=ref_file.name,
                                cfg_weight=cfg_weight,
                                exaggeration=exaggeration,
                                temperature=temperature
                            )
                    finally:
                        # Clean up temp file
                        os.unlink(ref_file.name)
            else:
                # Standard synthesis without voice cloning
                logger.info("🗣️ Using standard voice synthesis")
                if language != "en" and model == self.models.get("multilingual"):
                    wav = model.generate(
                        text=text,
                        language=language,
                        cfg_weight=cfg_weight,
                        exaggeration=exaggeration,
                        temperature=temperature
                    )
                else:
                    wav = model.generate(
                        text=text,
                        cfg_weight=cfg_weight,
                        exaggeration=exaggeration,
                        temperature=temperature
                    )
            
            # Convert to numpy array if needed
            if torch.is_tensor(wav):
                wav = wav.cpu().numpy()
            elif isinstance(wav, list):
                wav = np.array(wav)
            
            logger.info(f"✅ Speech generated successfully: {len(wav)} samples")
            return wav
            
        except Exception as e:
            logger.error(f"❌ Speech synthesis failed: {e}")
            return None

# Global service instance
tts_service = ChatterboxTTSService()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    voice_profile: str = Field("assistant_female", description="Voice profile to use")
    language: str = Field("en", description="Language code (en, es, fr, etc.)")
    cfg_weight: float = Field(0.5, ge=0.1, le=1.0, description="Config weight for generation control")
    exaggeration: float = Field(0.5, ge=0.0, le=1.0, description="Emotion exaggeration level")
    temperature: float = Field(1.0, ge=0.5, le=2.0, description="Temperature for generation diversity")
    audio_format: str = Field("wav", description="Output format: wav, mp3, or ogg")

class VoiceCloneRequest(BaseModel):
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    language: str = Field("en", description="Language code")
    cfg_weight: float = Field(0.5, ge=0.1, le=1.0, description="Config weight")
    exaggeration: float = Field(0.5, ge=0.0, le=1.0, description="Emotion exaggeration")
    temperature: float = Field(1.0, ge=0.5, le=2.0, description="Generation temperature")
    audio_format: str = Field("wav", description="Output format")

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
        logger.error(f"❌ Audio conversion failed: {e}")
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
    """Health check endpoint for load balancers"""
    try:
        # Calculate startup time
        startup_time = time.time() - (getattr(app.state, 'startup_time', time.time()))
        
        health_data = {
            "ok": True,
            "service": "june-chatterbox-tts",
            "timestamp": time.time(),
            "status": "healthy",
            "chatterbox_available": CHATTERBOX_AVAILABLE,
            "device": config.device,
            "multilingual_enabled": config.enable_multilingual,
            "supported_languages": tts_service.supported_languages,
            "voice_profiles": list(VOICE_PROFILES.keys()),
            "engine": "chatterbox-tts",
            "features": {
                "emotion_control": True,
                "voice_cloning": True,
                "multilingual": config.enable_multilingual,
                "watermarking": True
            },
            "startup_time": startup_time
        }
        
        # Check if TTS service is properly initialized
        if not tts_service.is_initialized:
            # During startup period (first 5 minutes), return initializing status
            if startup_time < 300:  # 5 minutes grace period
                health_data.update({
                    "status": "initializing",
                    "message": "Chatterbox models are loading, please wait...",
                    "estimated_ready_in": max(0, 300 - startup_time)
                })
                return health_data  # Return 200 but with initializing status
            else:
                health_data.update({
                    "status": "unhealthy",
                    "message": "Chatterbox initialization failed or timed out"
                })
                return health_data
        
        # Service is ready
        health_data.update({
            "models_loaded": True,
            "ready_for_synthesis": True
        })
        
        return health_data
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            "ok": False,
            "service": "june-chatterbox-tts",
            "timestamp": time.time(),
            "status": "unhealthy",
            "error": str(e)
        }

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    # Track startup time for health checks
    app.state.startup_time = time.time()
    
    logger.info("🚀 Starting June Chatterbox TTS Service...")
    
    success = await tts_service.initialize()
    if success:
        logger.info("✅ Chatterbox TTS service initialized successfully")
    else:
        logger.error("❌ Failed to initialize Chatterbox TTS service")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-chatterbox-tts",
        "status": "running",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "engine": "chatterbox-tts",
        "version": "1.0.0",
        "license": "MIT",
        "features": {
            "multilingual": config.enable_multilingual,
            "voice_profiles": True,
            "emotion_control": True,
            "voice_cloning": True,
            "watermarking": True,
            "real_time": True
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
                "emotion_preset": profile.emotion_preset
            }
            for name, profile in VOICE_PROFILES.items()
        },
        "default": "assistant_female",
        "engine": "chatterbox-tts",
        "features": {
            "multilingual": True,
            "emotion_control": True,
            "voice_cloning": True,
            "watermarking": True
        }
    }

@app.get("/v1/languages")
async def list_languages():
    """List supported languages"""
    return {
        "languages": tts_service.supported_languages,
        "multilingual_enabled": config.enable_multilingual,
        "default_language": config.default_language,
        "engine": "chatterbox-tts"
    }

# Service-to-Service TTS Endpoint (Compatible with existing orchestrator)
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("assistant_female", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed (mapped to cfg_weight)"),
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
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Map voice parameter to voice profile
        voice_profile = voice if voice in VOICE_PROFILES else "assistant_female"
        
        # Map speed to cfg_weight (inverse relationship for Chatterbox)
        cfg_weight = 1.0 / speed if speed > 0 else 0.5
        cfg_weight = max(0.1, min(1.0, cfg_weight))
        
        # Generate speech
        audio_data = await tts_service.synthesize(
            text=text,
            voice_profile=voice_profile,
            language=language,
            cfg_weight=cfg_weight
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Chatterbox default sample rate
        sample_rate = 24000
        
        # Convert to requested format
        audio_bytes = convert_audio_format(audio_data, sample_rate, audio_encoding)
        
        # Determine media type
        media_type = determine_media_type(audio_encoding)
        
        logger.info(f"✅ Chatterbox TTS synthesis successful: {len(audio_bytes)} bytes generated")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{audio_encoding.lower()}",
                "X-Processed-By": "june-chatterbox-tts",
                "X-Caller-Service": calling_service,
                "X-TTS-Engine": "chatterbox-tts",
                "X-Voice-Profile": voice_profile,
                "X-Audio-Length": str(len(audio_data)),
                "X-Features": "emotion-control,voice-cloning,watermarking"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chatterbox TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Advanced TTS endpoint with full Chatterbox features
@app.post("/v1/tts/advanced")
async def synthesize_speech_advanced(
    request: TTSRequest,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Advanced TTS endpoint with full Chatterbox features"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎭 Advanced TTS request from {calling_service}")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Generate speech with advanced parameters
        audio_data = await tts_service.synthesize(
            text=request.text,
            voice_profile=request.voice_profile,
            language=request.language,
            cfg_weight=request.cfg_weight,
            exaggeration=request.exaggeration,
            temperature=request.temperature
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Chatterbox sample rate
        sample_rate = 24000
        
        # Convert to requested format
        audio_bytes = convert_audio_format(audio_data, sample_rate, request.audio_format)
        media_type = determine_media_type(request.audio_format)
        
        logger.info(f"✅ Advanced Chatterbox TTS synthesis successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "X-TTS-Engine": "chatterbox-tts",
                "X-Voice-Profile": request.voice_profile,
                "X-Language": request.language,
                "X-Caller-Service": calling_service,
                "X-Emotion-Config": f"cfg={request.cfg_weight},exag={request.exaggeration},temp={request.temperature}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Advanced Chatterbox TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Voice cloning endpoint
@app.post("/v1/tts/clone")
async def voice_clone_synthesis(
    request: VoiceCloneRequest,
    reference_audio: UploadFile = File(..., description="Reference audio file for voice cloning"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning endpoint using reference audio"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if not config.enable_voice_cloning:
            raise HTTPException(status_code=400, detail="Voice cloning not enabled")
        
        logger.info(f"🎤 Voice cloning request from {calling_service}")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Read reference audio
        reference_audio_data = await reference_audio.read()
        
        # Generate speech with voice cloning
        audio_data = await tts_service.synthesize(
            text=request.text,
            voice_profile="assistant_female",  # Base profile
            language=request.language,
            reference_audio=reference_audio_data,
            cfg_weight=request.cfg_weight,
            exaggeration=request.exaggeration,
            temperature=request.temperature
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Voice cloning failed")
        
        sample_rate = 24000
        audio_bytes = convert_audio_format(audio_data, sample_rate, request.audio_format)
        media_type = determine_media_type(request.audio_format)
        
        logger.info(f"✅ Voice cloning synthesis successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "X-TTS-Engine": "chatterbox-tts",
                "X-Feature": "voice-cloning",
                "X-Language": request.language,
                "X-Caller-Service": calling_service,
                "X-Reference-Audio-Size": str(len(reference_audio_data))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))