# File: June/services/june-tts/app.py
# Complete Chatterbox TTS Service - Official Implementation

import os
import io
import time
import logging
import tempfile
import base64
from typing import Optional, Dict, Any
from pathlib import Path

import torchaudio as ta
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import Chatterbox TTS using official method
try:
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    CHATTERBOX_AVAILABLE = True
    logging.info("✅ Chatterbox TTS imported successfully")
except ImportError as e:
    CHATTERBOX_AVAILABLE = False
    logging.error(f"❌ Chatterbox TTS not available: {e}")

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
        self.device = os.getenv("DEVICE", "cuda" if CHATTERBOX_AVAILABLE else "cpu")
        self.enable_multilingual = os.getenv("ENABLE_MULTILINGUAL", "true").lower() == "true"
        self.max_text_length = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
        
        logger.info(f"TTS Config - Device: {self.device}, Multilingual: {self.enable_multilingual}")

config = TTSConfig()

# =============================================================================
# CHATTERBOX TTS SERVICE
# =============================================================================

class ChatterboxTTSService:
    def __init__(self):
        self.english_model = None
        self.multilingual_model = None
        self.is_initialized = False
        self.supported_languages = ["en"]
        
    async def initialize(self):
        """Initialize Chatterbox TTS models using official method"""
        if not CHATTERBOX_AVAILABLE:
            logger.error("❌ Chatterbox TTS not available")
            return False
            
        try:
            logger.info("🎤 Initializing Chatterbox TTS...")
            
            # Initialize English model (always available)
            logger.info("📥 Loading Chatterbox English model...")
            self.english_model = ChatterboxTTS.from_pretrained(device=config.device)
            logger.info("✅ English model loaded")
            
            # Initialize multilingual model if enabled
            if config.enable_multilingual:
                try:
                    logger.info("📥 Loading Chatterbox Multilingual model...")
                    self.multilingual_model = ChatterboxMultilingualTTS.from_pretrained(device=config.device)
                    self.supported_languages = [
                        "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", 
                        "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", 
                        "sw", "tr", "zh"
                    ]
                    logger.info("✅ Multilingual model loaded")
                except Exception as e:
                    logger.warning(f"⚠️ Multilingual model failed: {e}")
            
            self.is_initialized = True
            logger.info("🎉 Chatterbox TTS fully initialized!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False
    
    async def synthesize(self, text: str, language: str = "en", 
                        exaggeration: float = 0.5, cfg_weight: float = 0.5,
                        temperature: float = 1.0, reference_audio_path: str = None) -> Optional[bytes]:
        """Synthesize speech using official Chatterbox method"""
        
        if not self.is_initialized:
            logger.error("❌ Service not initialized")
            return None
            
        try:
            # Choose model based on language
            if language == "en" or not self.multilingual_model:
                model = self.english_model
                logger.info(f"🗣️ Using English model for: '{text[:50]}...'")
            else:
                model = self.multilingual_model
                logger.info(f"🌍 Using multilingual model for {language}: '{text[:50]}...'")
            
            # Generate audio using official Chatterbox API
            if reference_audio_path:
                # Voice cloning
                wav = model.generate(
                    text=text,
                    reference_path=reference_audio_path,
                    language=language if language != "en" else None,
                    exaggeration=exaggeration,
                    cfg_weight=cfg_weight,
                    temperature=temperature
                )
            else:
                # Standard generation
                if language != "en" and self.multilingual_model:
                    wav = model.generate(
                        text=text,
                        language=language,
                        exaggeration=exaggeration,
                        cfg_weight=cfg_weight,
                        temperature=temperature
                    )
                else:
                    wav = model.generate(
                        text=text,
                        exaggeration=exaggeration,
                        cfg_weight=cfg_weight,
                        temperature=temperature
                    )
            
            # Convert to audio bytes using torchaudio (official method)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                ta.save(tmp_file.name, wav, model.sr)
                
                with open(tmp_file.name, "rb") as f:
                    audio_bytes = f.read()
                
                os.unlink(tmp_file.name)
            
            logger.info(f"✅ Generated {len(audio_bytes)} bytes of audio")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            return None

# Global service instance
tts_service = ChatterboxTTSService()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    language: str = Field("en", description="Language code")
    exaggeration: float = Field(0.5, ge=0.0, le=1.0, description="Emotion exaggeration")
    cfg_weight: float = Field(0.5, ge=0.0, le=1.0, description="Config weight")
    temperature: float = Field(1.0, ge=0.5, le=2.0, description="Temperature")

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    startup_time = time.time() - getattr(app.state, 'startup_time', time.time())
    
    return {
        "ok": True,
        "service": "june-chatterbox-tts",
        "timestamp": time.time(),
        "status": "healthy" if tts_service.is_initialized else "initializing",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "device": config.device,
        "supported_languages": tts_service.supported_languages,
        "engine": "chatterbox-official",
        "startup_time": startup_time,
        "features": {
            "emotion_control": True,
            "voice_cloning": True,
            "multilingual": config.enable_multilingual,
            "watermarking": True
        }
    }

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    app.state.startup_time = time.time()
    logger.info("🚀 Starting Chatterbox TTS Service...")
    
    success = await tts_service.initialize()
    if success:
        logger.info("✅ Service ready")
    else:
        logger.error("❌ Service failed to initialize")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-chatterbox-tts",
        "status": "running",
        "engine": "chatterbox-official",
        "version": "1.0.0",
        "license": "MIT",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "supported_languages": tts_service.supported_languages
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voice profiles"""
    return {
        "voices": {
            "assistant_female": {"name": "Assistant Female", "description": "Default female voice"},
            "assistant_male": {"name": "Assistant Male", "description": "Default male voice"}
        },
        "default": "assistant_female",
        "engine": "chatterbox-official"
    }

@app.get("/v1/languages")
async def list_languages():
    """List supported languages"""
    return {
        "languages": tts_service.supported_languages,
        "default_language": "en",
        "engine": "chatterbox-official"
    }

# Main TTS endpoint (compatible with orchestrator)
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
        if len(text) > config.max_text_length:
            raise HTTPException(status_code=400, detail=f"Text too long (max {config.max_text_length} characters)")
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:50]}...'")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Map speed to cfg_weight (inverse relationship for better control)
        cfg_weight = 1.0 / speed if speed > 0 else 0.5
        cfg_weight = max(0.1, min(1.0, cfg_weight))
        
        # Generate speech using official Chatterbox
        audio_bytes = await tts_service.synthesize(
            text=text,
            language=language,
            cfg_weight=cfg_weight,
            exaggeration=0.5,  # Default emotion level
            temperature=1.0
        )
        
        if audio_bytes is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Convert to requested format if needed
        media_type = "audio/mpeg" if audio_encoding.upper() == "MP3" else "audio/wav"
        
        # For MP3 conversion, we'd need additional processing
        if audio_encoding.upper() == "MP3":
            # For now, return WAV (add MP3 conversion later if needed)
            media_type = "audio/wav"
        
        logger.info(f"✅ Chatterbox synthesis successful: {len(audio_bytes)} bytes")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{audio_encoding.lower()}",
                "X-TTS-Engine": "chatterbox-official",
                "X-Caller-Service": calling_service,
                "X-Features": "emotion-control,voice-cloning,watermarking"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Advanced TTS endpoint with full Chatterbox features
@app.post("/v1/tts/advanced")
async def synthesize_speech_advanced(
    request: TTSRequest,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Advanced TTS endpoint with full Chatterbox emotion control"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎭 Advanced TTS request from {calling_service}")
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Generate speech with advanced parameters
        audio_bytes = await tts_service.synthesize(
            text=request.text,
            language=request.language,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            temperature=request.temperature
        )
        
        if audio_bytes is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        logger.info(f"✅ Advanced synthesis successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers={
                "X-TTS-Engine": "chatterbox-official",
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
        
        if not tts_service.is_initialized:
            raise HTTPException(status_code=503, detail="Chatterbox TTS service not ready")
        
        # Save reference audio to temporary file
        reference_audio_data = await reference_audio.read()
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
            ref_file.write(reference_audio_data)
            ref_file.flush()
            
            # Generate speech with voice cloning
            audio_bytes = await tts_service.synthesize(
                text=text,
                language=language,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
                reference_audio_path=ref_file.name
            )
            
            # Clean up temp file
            os.unlink(ref_file.name)
        
        if audio_bytes is None:
            raise HTTPException(status_code=500, detail="Voice cloning failed")
        
        logger.info(f"✅ Voice cloning successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers={
                "X-TTS-Engine": "chatterbox-official",
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