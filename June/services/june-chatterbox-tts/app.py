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

# Chatterbox TTS imports
try:
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    CHATTERBOX_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Chatterbox TTS not available: {e}")
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

class ChatterboxConfig:
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

config = ChatterboxConfig()

# =============================================================================
# VOICE PROFILES AND MANAGEMENT
# =============================================================================

class VoiceProfile:
    def __init__(self, name: str, description: str, audio_path: Optional[str] = None, 
                 language: str = "en", emotion_preset: Dict[str, float] = None):
        self.name = name
        self.description = description
        self.audio_path = audio_path
        self.language = language
        self.emotion_preset = emotion_preset or {
            "exaggeration": 0.5,
            "cfg_weight": 0.5,
            "temperature": 1.0
        }

# Predefined voice profiles
VOICE_PROFILES = {
    "assistant_female": VoiceProfile(
        name="Assistant Female",
        description="Professional female assistant voice",
        language="en",
        emotion_preset={"exaggeration": 0.3, "cfg_weight": 0.6, "temperature": 0.8}
    ),
    "assistant_male": VoiceProfile(
        name="Assistant Male", 
        description="Professional male assistant voice",
        language="en",
        emotion_preset={"exaggeration": 0.3, "cfg_weight": 0.6, "temperature": 0.8}
    ),
    "narrator_warm": VoiceProfile(
        name="Warm Narrator",
        description="Warm, storytelling voice",
        language="en", 
        emotion_preset={"exaggeration": 0.7, "cfg_weight": 0.4, "temperature": 1.1}
    ),
    "narrator_dramatic": VoiceProfile(
        name="Dramatic Narrator",
        description="Dramatic, expressive voice for storytelling",
        language="en",
        emotion_preset={"exaggeration": 1.2, "cfg_weight": 0.3, "temperature": 1.3}
    ),
    "conversation_friendly": VoiceProfile(
        name="Friendly Conversational",
        description="Casual, friendly conversation voice",
        language="en",
        emotion_preset={"exaggeration": 0.6, "cfg_weight": 0.5, "temperature": 1.0}
    )
}

# =============================================================================
# MODELS AND INITIALIZATION
# =============================================================================

class ChatterboxService:
    def __init__(self):
        self.model = None
        self.multilingual_model = None
        self.is_initialized = False
        self.supported_languages = ["en"]
        
    async def initialize(self):
        """Initialize Chatterbox models"""
        if not CHATTERBOX_AVAILABLE:
            logger.error("Chatterbox TTS not available - using fallback")
            return False
            
        try:
            logger.info(f"Initializing Chatterbox TTS on device: {config.device}")
            
            # Initialize English model
            self.model = ChatterboxTTS.from_pretrained(device=config.device)
            logger.info("✅ English Chatterbox model loaded successfully")
            
            # Initialize multilingual model if enabled
            if config.enable_multilingual:
                try:
                    self.multilingual_model = ChatterboxMultilingualTTS.from_pretrained(device=config.device)
                    self.supported_languages = [
                        "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
                        "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
                        "th", "tr", "zh"
                    ]
                    logger.info("✅ Multilingual Chatterbox model loaded successfully")
                except Exception as e:
                    logger.warning(f"Failed to load multilingual model: {e}")
                    self.multilingual_model = None
            
            self.is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Chatterbox: {e}")
            return False
    
    def get_model_for_language(self, language: str = "en"):
        """Get the appropriate model for the given language"""
        if language == "en":
            return self.model
        elif self.multilingual_model and language in self.supported_languages:
            return self.multilingual_model
        else:
            logger.warning(f"Language {language} not supported, falling back to English")
            return self.model
    
    async def synthesize(self, text: str, voice_profile: str = "assistant_female",
                        audio_prompt_path: Optional[str] = None, language: str = "en",
                        exaggeration: float = None, cfg_weight: float = None,
                        temperature: float = None, speed_factor: float = 1.0,
                        seed: Optional[int] = None) -> Optional[np.ndarray]:
        """Synthesize speech using Chatterbox"""
        
        if not self.is_initialized:
            logger.error("Chatterbox service not initialized")
            return None
            
        try:
            # Get model for language
            model = self.get_model_for_language(language)
            if not model:
                logger.error(f"No model available for language: {language}")
                return None
            
            # Get voice profile settings
            profile = VOICE_PROFILES.get(voice_profile, VOICE_PROFILES["assistant_female"])
            
            # Apply emotion settings
            emotion_settings = profile.emotion_preset.copy()
            if exaggeration is not None:
                emotion_settings["exaggeration"] = exaggeration
            if cfg_weight is not None:
                emotion_settings["cfg_weight"] = cfg_weight  
            if temperature is not None:
                emotion_settings["temperature"] = temperature
            
            # Set seed for reproducibility
            if seed is not None:
                torch.manual_seed(seed)
                
            # Generate speech
            generation_kwargs = {
                "exaggeration": emotion_settings["exaggeration"],
                "cfg_weight": emotion_settings["cfg_weight"], 
                "temperature": emotion_settings["temperature"]
            }
            
            if audio_prompt_path and os.path.exists(audio_prompt_path):
                generation_kwargs["audio_prompt_path"] = audio_prompt_path
                
            if language != "en" and self.multilingual_model:
                generation_kwargs["language_id"] = language
            
            logger.info(f"Generating speech with settings: {generation_kwargs}")
            
            # Generate audio
            wav = model.generate(text, **generation_kwargs)
            
            # Apply speed factor if needed
            if speed_factor != 1.0 and speed_factor > 0:
                # Simple time stretching (you might want to use more sophisticated methods)
                new_length = int(len(wav) / speed_factor)
                wav = torch.nn.functional.interpolate(
                    wav.unsqueeze(0).unsqueeze(0), 
                    size=new_length, 
                    mode='linear'
                ).squeeze()
            
            logger.info(f"✅ Speech generated successfully: {len(wav)} samples")
            return wav.cpu().numpy()
            
        except Exception as e:
            logger.error(f"Speech synthesis failed: {e}")
            return None

# Global service instance
chatterbox_service = ChatterboxService()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    voice_profile: str = Field("assistant_female", description="Voice profile to use")
    language: str = Field("en", description="Language code (en, es, fr, etc.)")
    exaggeration: Optional[float] = Field(None, ge=0.0, le=2.0, description="Emotion exaggeration (0.0-2.0)")
    cfg_weight: Optional[float] = Field(None, ge=0.0, le=1.0, description="Generation guidance (0.0-1.0)")
    temperature: Optional[float] = Field(None, ge=0.1, le=2.0, description="Generation randomness (0.1-2.0)")
    speed_factor: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    audio_format: str = Field("wav", description="Output format: wav, mp3, or ogg")
    seed: Optional[int] = Field(None, description="Random seed for reproducible generation")

class VoiceCloneRequest(BaseModel):
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    language: str = Field("en", description="Language code")
    exaggeration: Optional[float] = Field(0.5, ge=0.0, le=2.0, description="Emotion exaggeration")
    cfg_weight: Optional[float] = Field(0.5, ge=0.0, le=1.0, description="Generation guidance")
    temperature: Optional[float] = Field(1.0, ge=0.1, le=2.0, description="Generation randomness")
    speed_factor: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    audio_format: str = Field("wav", description="Output format: wav, mp3, or ogg")

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

async def save_uploaded_audio(audio_file: UploadFile) -> str:
    """Save uploaded audio file and return path"""
    
    # Validate file type
    if not audio_file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="File must be audio format")
    
    # Create unique filename
    file_hash = hashlib.md5(f"{audio_file.filename}{time.time()}".encode()).hexdigest()[:8]
    filename = f"voice_clone_{file_hash}.wav"
    file_path = config.cache_path / filename
    
    # Save file
    async with aiofiles.open(file_path, "wb") as f:
        content = await audio_file.read()
        await f.write(content)
    
    logger.info(f"Saved uploaded audio: {file_path}")
    return str(file_path)

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
        
        elif target_format.lower() == "ogg":
            # Convert to OGG
            buffer = io.BytesIO()
            sf.write(buffer, audio_data, sample_rate, format='OGG')
            return buffer.getvalue()
        
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

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    logger.info("Starting June Chatterbox TTS Service...")
    
    success = await chatterbox_service.initialize()
    if success:
        logger.info("✅ Chatterbox TTS service initialized successfully")
    else:
        logger.error("❌ Failed to initialize Chatterbox TTS service")

@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    return {
        "ok": True,
        "service": "june-chatterbox-tts",
        "timestamp": time.time(),
        "status": "healthy" if chatterbox_service.is_initialized else "initializing",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "device": config.device,
        "multilingual_enabled": config.enable_multilingual,
        "supported_languages": chatterbox_service.supported_languages,
        "voice_profiles": list(VOICE_PROFILES.keys())
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-chatterbox-tts",
        "status": "running",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "features": {
            "emotion_control": config.enable_emotion_control,
            "voice_cloning": config.enable_voice_cloning,
            "multilingual": config.enable_multilingual,
            "neural_watermarking": True
        },
        "supported_languages": chatterbox_service.supported_languages,
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
        "engine": "chatterbox",
        "features": {
            "emotion_control": True,
            "voice_cloning": True,
            "multilingual": config.enable_multilingual,
            "speed_control": True,
            "neural_watermarking": True
        }
    }

@app.get("/v1/languages")
async def list_languages():
    """List supported languages"""
    return {
        "languages": chatterbox_service.supported_languages,
        "multilingual_enabled": config.enable_multilingual,
        "default_language": config.default_language
    }

# Service-to-Service TTS Endpoint (Compatible with existing orchestrator)
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("assistant_female", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_encoding: str = Query("MP3", description="Audio format: MP3, WAV, or OGG"),
    language: str = Query("en", description="Language code"),
    exaggeration: float = Query(0.5, ge=0.0, le=2.0, description="Emotion exaggeration"),
    cfg_weight: float = Query(0.5, ge=0.0, le=1.0, description="Generation guidance"),
    temperature: float = Query(1.0, ge=0.1, le=2.0, description="Generation randomness"),
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
        
        if not chatterbox_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        # Map voice parameter to voice profile
        voice_profile = voice if voice in VOICE_PROFILES else "assistant_female"
        
        # Generate speech
        audio_data = await chatterbox_service.synthesize(
            text=text,
            voice_profile=voice_profile,
            language=language,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
            speed_factor=speed
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Get sample rate
        model = chatterbox_service.get_model_for_language(language)
        sample_rate = getattr(model, 'sr', 24000)
        
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
                "X-TTS-Engine": "chatterbox",
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
    """Advanced TTS endpoint with full Chatterbox features"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        logger.info(f"🎭 Advanced TTS request from {calling_service}")
        
        if not chatterbox_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        # Generate speech
        audio_data = await chatterbox_service.synthesize(
            text=request.text,
            voice_profile=request.voice_profile,
            language=request.language,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            temperature=request.temperature,
            speed_factor=request.speed_factor,
            seed=request.seed
        )
        
        if audio_data is None:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Get sample rate
        model = chatterbox_service.get_model_for_language(request.language)
        sample_rate = getattr(model, 'sr', 24000)
        
        # Convert to requested format
        audio_bytes = convert_audio_format(audio_data, sample_rate, request.audio_format)
        media_type = determine_media_type(request.audio_format)
        
        logger.info(f"✅ Advanced TTS synthesis successful")
        
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={
                "X-TTS-Engine": "chatterbox",
                "X-Voice-Profile": request.voice_profile,
                "X-Language": request.language,
                "X-Exaggeration": str(request.exaggeration or "default"),
                "X-Caller-Service": calling_service
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Advanced TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Voice cloning endpoint
@app.post("/v1/voice-clone")
async def clone_voice(
    audio_file: UploadFile = File(..., description="Reference audio file"),
    text: str = Form(..., description="Text to synthesize"),
    language: str = Form("en", description="Language code"),
    exaggeration: float = Form(0.5, ge=0.0, le=2.0, description="Emotion exaggeration"),
    cfg_weight: float = Form(0.5, ge=0.0, le=1.0, description="Generation guidance"),
    temperature: float = Form(1.0, ge=0.1, le=2.0, description="Generation randomness"),
    speed_factor: float = Form(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_format: str = Form("wav", description="Output format"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning endpoint - clone voice from reference audio"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if not config.enable_voice_cloning:
            raise HTTPException(status_code=403, detail="Voice cloning is disabled")
        
        if not chatterbox_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        logger.info(f"🎤 Voice cloning request from {calling_service}")
        
        # Save uploaded audio
        audio_path = await save_uploaded_audio(audio_file)
        
        try:
            # Generate speech with voice cloning
            audio_data = await chatterbox_service.synthesize(
                text=text,
                audio_prompt_path=audio_path,
                language=language,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
                speed_factor=speed_factor
            )
            
            if audio_data is None:
                raise HTTPException(status_code=500, detail="Voice cloning failed")
            
            # Get sample rate
            model = chatterbox_service.get_model_for_language(language)
            sample_rate = getattr(model, 'sr', 24000)
            
            # Convert to requested format
            audio_bytes = convert_audio_format(audio_data, sample_rate, audio_format)
            media_type = determine_media_type(audio_format)
            
            logger.info(f"✅ Voice cloning successful")
            
            return StreamingResponse(
                io.BytesIO(audio_bytes),
                media_type=media_type,
                headers={
                    "X-TTS-Engine": "chatterbox",
                    "X-Feature": "voice-cloning",
                    "X-Language": language,
                    "X-Caller-Service": calling_service
                }
            )
            
        finally:
            # Clean up temporary audio file
            try:
                os.unlink(audio_path)
            except:
                pass
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Batch TTS endpoint
@app.post("/v1/tts/batch")
async def batch_synthesize(
    texts: List[str] = Query(..., description="List of texts to synthesize"),
    voice_profile: str = Query("assistant_female", description="Voice profile"),
    language: str = Query("en", description="Language code"),
    audio_format: str = Query("wav", description="Output format"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Batch TTS synthesis for multiple texts"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if not chatterbox_service.is_initialized:
            raise HTTPException(status_code=503, detail="TTS service not ready")
        
        if len(texts) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 texts per batch")
        
        logger.info(f"📚 Batch TTS request from {calling_service}: {len(texts)} texts")
        
        results = []
        
        for i, text in enumerate(texts):
            if len(text) > config.max_text_length:
                results.append({"error": f"Text {i} too long"})
                continue
            
            # Generate speech
            audio_data = await chatterbox_service.synthesize(
                text=text,
                voice_profile=voice_profile,
                language=language
            )
            
            if audio_data is None:
                results.append({"error": f"Synthesis failed for text {i}"})
                continue
            
            # Get sample rate and convert
            model = chatterbox_service.get_model_for_language(language)
            sample_rate = getattr(model, 'sr', 24000)
            audio_bytes = convert_audio_format(audio_data, sample_rate, audio_format)
            
            # Encode to base64 for JSON response
            audio_b64 = base64.b64encode(audio_bytes).decode()
            
            results.append({
                "index": i,
                "text": text[:50] + "..." if len(text) > 50 else text,
                "audio_data": audio_b64,
                "audio_length": len(audio_data),
                "success": True
            })
        
        logger.info(f"✅ Batch TTS completed: {len(results)} results")
        
        return {
            "results": results,
            "total_texts": len(texts),
            "successful": len([r for r in results if r.get("success")]),
            "failed": len([r for r in results if "error" in r]),
            "audio_format": audio_format,
            "voice_profile": voice_profile,
            "language": language
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch TTS failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# File: June/services/june-chatterbox-tts/shared/__init__.py

# Shared modules package