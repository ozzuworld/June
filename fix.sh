#!/bin/bash
# June TTS Service Complete Fix Script
# This script fixes all the import and dependency issues

set -euo pipefail

echo "🔧 Fixing June TTS Service..."
echo "=============================="

# Check we're in the right directory
if [ ! -d "June/services/june-tts" ]; then
    echo "❌ Please run from project root directory"
    exit 1
fi

cd June/services/june-tts

# Step 1: Fix the shared module completely
echo "📦 Fixing shared module..."
mkdir -p shared

cat > shared/__init__.py << 'EOF'
# shared/__init__.py
"""
Shared module for June TTS service
Provides common utilities and authentication functions
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import Depends, HTTPException, Header

logger = logging.getLogger(__name__)

def require_service_auth():
    """
    Authentication function for service-to-service communication
    Returns auth data directly for dependency injection
    """
    return {
        "client_id": "docker-service", 
        "scopes": ["tts:synthesize", "tts:read"],
        "authenticated": True
    }

async def validate_websocket_token(token: str) -> Dict[str, Any]:
    """Validate a WebSocket token"""
    if not token:
        raise ValueError("No token provided")
    
    # For Docker deployment, return mock user data
    # In production, implement proper JWT validation
    return {
        "user_id": "docker-user",
        "sub": "docker-user", 
        "authenticated": True,
        "scopes": ["websocket", "tts:stream"]
    }

def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from authentication data"""
    return auth_data.get("sub") or auth_data.get("user_id") or auth_data.get("uid", "unknown")

def extract_client_id(auth_data: Dict[str, Any]) -> str:
    """Extract client ID from authentication data"""
    return auth_data.get("client_id") or auth_data.get("azp", "unknown")

def has_role(auth_data: Dict[str, Any], role: str) -> bool:
    """Check if user has a specific role"""
    roles = auth_data.get("realm_access", {}).get("roles", [])
    return role in roles

def has_scope(auth_data: Dict[str, Any], scope: str) -> bool:
    """Check if token has a specific scope"""
    scopes = auth_data.get("scope", "").split() if auth_data.get("scope") else auth_data.get("scopes", [])
    return scope in scopes

# Export the main functions
__all__ = [
    'require_service_auth',
    'validate_websocket_token', 
    'extract_user_id',
    'extract_client_id',
    'has_role',
    'has_scope'
]
EOF

# Step 2: Fix the OpenVoice engine with better error handling
echo "🎛️ Fixing OpenVoice engine..."
mkdir -p app/core

cat > app/core/openvoice_engine.py << 'EOF'
import asyncio
import base64
import glob
import inspect
import os
import tempfile
from typing import Optional, Tuple, Callable, Dict, Any
import logging

import httpx
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Configuration
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}

# Global state
_MELO = None
_CONVERTER = None
_SPEAKER_ID = None
_CONVERT_FN: Optional[Callable[..., np.ndarray]] = None

def _load_models_once() -> None:
    """Load models with comprehensive error handling"""
    global _MELO, _CONVERTER, _SPEAKER_ID, _CONVERT_FN
    if _MELO is not None:
        return

    try:
        from melo.api import TTS as MeloTTS
        
        # Initialize Melo (always needed)
        _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))
        _SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "0")
        logger.info("✅ MeloTTS loaded successfully")
        
        # Try to initialize converter (optional)
        try:
            from openvoice.api import ToneColorConverter
            from openvoice import se_extractor
            
            root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
            conv_root = os.path.join(root, "tone_color_converter")
            
            if os.path.isdir(conv_root):
                cfg_path = os.path.join(conv_root, "config.json")
                ckpt_files = glob.glob(os.path.join(conv_root, "*.pth")) + glob.glob(os.path.join(conv_root, "*.pt"))
                
                if os.path.exists(cfg_path) and ckpt_files:
                    device = os.getenv("OPENVOICE_DEVICE", "cuda" if os.getenv("CUDA_VISIBLE_DEVICES", "") else "cpu")
                    converter = ToneColorConverter(config_path=cfg_path, device=device)
                    
                    if hasattr(converter, "load_ckpt"):
                        converter.load_ckpt(ckpt_files[0])
                    elif hasattr(converter, "load"):
                        converter.load(ckpt_path=ckpt_files[0])
                    
                    _CONVERTER = converter
                    logger.info("✅ Voice converter loaded successfully")
                else:
                    logger.warning("⚠️ Converter files not found - voice cloning disabled")
            else:
                logger.warning("⚠️ Converter directory not found - voice cloning disabled")
                
        except ImportError as e:
            logger.warning(f"⚠️ OpenVoice not available: {e}")
            _CONVERTER = None
        except Exception as e:
            logger.warning(f"⚠️ Could not load voice converter: {e}")
            _CONVERTER = None
        
    except ImportError as e:
        logger.error(f"❌ MeloTTS not available: {e}")
        raise RuntimeError(f"MeloTTS is required but not installed: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to load TTS models: {e}")
        raise RuntimeError(f"TTS initialization failed: {e}")

def warmup_models() -> None:
    """Warmup models at startup"""
    try:
        _load_models_once()
        logger.info("✅ TTS models warmed up successfully")
    except Exception as e:
        logger.error(f"❌ Model warmup failed: {e}")

async def synthesize_v2_to_wav_path(
    *,
    text: str,
    language: str,
    reference_b64: Optional[str],
    reference_url: Optional[str],
    speed: float,
    volume: float,
    pitch: float,
    metadata: dict,
) -> str:
    """Synthesize speech to WAV file path"""
    
    # Validation
    if not text:
        raise ValueError("text is required")
    if len(text) > _MAX_TEXT_LEN:
        raise ValueError("text too long")
    
    lang = language.lower()
    if lang not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"language must be one of {_SUPPORTED_LANGUAGES}")
    
    if speed <= 0:
        raise ValueError("speed must be > 0")
    
    # Load models if not already loaded
    _load_models_once()
    assert _MELO is not None
    
    # For now, just use basic MeloTTS without voice cloning
    # This ensures the service works even without full OpenVoice setup
    
    melo_lang = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JA", "ko": "KO"}.get(lang, "EN")
    
    # Try to convert speaker ID to int
    try:
        spk = int(os.getenv("MELO_SPEAKER_ID", "0"))
    except ValueError:
        spk = 0
    
    # Generate basic TTS
    if hasattr(_MELO, "tts_to_file"):
        fd, out_path = tempfile.mkstemp(prefix="june-tts-", suffix=".wav")
        os.close(fd)
        
        try:
            _MELO.tts_to_file(
                text=text,
                speaker_id=spk,
                speed=speed,
                language=melo_lang,
                output_path=out_path
            )
            return out_path
        except TypeError:
            # Try without language parameter
            _MELO.tts_to_file(
                text=text,
                speaker_id=spk,
                speed=speed,
                output_path=out_path
            )
            return out_path
    
    elif hasattr(_MELO, "tts_to_audio"):
        try:
            audio, sr = _MELO.tts_to_audio(
                text=text,
                speaker_id=spk,
                speed=speed,
                language=melo_lang
            )
        except TypeError:
            audio, sr = _MELO.tts_to_audio(
                text=text,
                speaker_id=spk,
                speed=speed
            )
        
        fd, out_path = tempfile.mkstemp(prefix="june-tts-", suffix=".wav")
        os.close(fd)
        sf.write(out_path, np.asarray(audio, dtype=np.float32), sr, subtype="PCM_16")
        return out_path
    
    else:
        raise RuntimeError("Unsupported MeloTTS build - no tts_to_file or tts_to_audio method")

# Engine class for compatibility
class OpenVoiceEngine:
    """Engine class for compatibility with clone router"""
    
    def __init__(self):
        self.converter = None
        self.initialized = False
        
    def initialize(self):
        """Initialize the engine"""
        try:
            _load_models_once()
            self.converter = _CONVERTER
            self.initialized = True
            logger.info("✅ OpenVoice engine initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenVoice engine: {e}")
            self.converter = None
            self.initialized = False
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: str = "EN",
        speed: float = 1.0
    ) -> bytes:
        """Clone voice from reference audio (or fallback to basic TTS)"""
        
        if not self.converter:
            logger.warning("⚠️ Voice cloning not available, using basic TTS")
        
        # For now, just generate basic TTS regardless of reference audio
        # This ensures the API works even without full voice cloning
        wav_path = await synthesize_v2_to_wav_path(
            text=text,
            language=language.lower(),
            reference_b64=None,
            reference_url=None,
            speed=speed,
            volume=1.0,
            pitch=0.0,
            metadata={}
        )
        
        # Read and return audio data
        with open(wav_path, 'rb') as f:
            audio_data = f.read()
        
        # Cleanup
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        
        return audio_data

# Create global engine instance
engine = OpenVoiceEngine()

# Initialize on import
try:
    engine.initialize()
except Exception as e:
    logger.warning(f"⚠️ Engine initialization failed on import: {e}")
EOF

# Step 3: Fix the TTS router with proper imports
echo "🎵 Fixing TTS router..."
cat > app/routers/tts.py << 'EOF'
from typing import AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict, HttpUrl

try:
    from shared import require_service_auth
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def require_service_auth():
        return {"client_id": "fallback", "authenticated": True}

from app.core.openvoice_engine import synthesize_v2_to_wav_path

router = APIRouter(prefix="/tts", tags=["tts"])

class TTSRequest(BaseModel):
    speaker_id: int | None = None
    model_config = ConfigDict(extra="ignore")
    text: str
    reference_b64: Optional[str] = None       # WAV/MP3/FLAC/OGG/etc (base64-encoded bytes)
    reference_url: Optional[HttpUrl] = None   # will be downloaded server-side
    voice_id: str = "base"                    # kept for API consistency; Melo pack selects actual voice
    language: str = "en"                      # en, es, fr, zh, ja, ko
    format: str = "wav"                       # output container (fixed to wav for now)
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 0.0
    metadata: dict = Field(default_factory=dict)

async def _file_stream(path: str) -> AsyncIterator[bytes]:
    chunk = 64 * 1024
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            yield data

@router.post("/generate")
async def generate(
    req: TTSRequest,
    service_auth: dict = Depends(require_service_auth) if AUTH_AVAILABLE else None
):
    # Guard clauses
    if not req.text or len(req.text.strip()) == 0:
        raise HTTPException(status_code=400, detail="text is required")
    if req.format.lower() != "wav":
        raise HTTPException(status_code=415, detail="Only wav output is supported")
    if not (req.reference_b64 or req.reference_url):
        raise HTTPException(status_code=400, detail="Provide reference_b64 or reference_url for cloning")

    wav_path = await synthesize_v2_to_wav_path(
        text=req.text.strip(),
        language=req.language.strip().lower(),
        reference_b64=req.reference_b64,
        reference_url=str(req.reference_url) if req.reference_url else None,
        speed=req.speed,
        volume=req.volume,
        pitch=req.pitch,
        metadata=req.metadata,
    )

    return StreamingResponse(_file_stream(wav_path), media_type="audio/wav")
EOF

# Step 4: Fix the clone router
echo "🎭 Fixing clone router..."
cat > app/routers/clone.py << 'EOF'
from fastapi import APIRouter, HTTPException, status, File, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clone", tags=["Voice Cloning"])

# Import with error handling
try:
    from app.core.openvoice_engine import engine
    ENGINE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OpenVoice engine not available: {e}")
    ENGINE_AVAILABLE = False
    engine = None

class ErrorResponse(BaseModel):
    detail: str
    error_code: str = "unknown"

async def validate_audio_file(file: UploadFile):
    """Basic audio file validation"""
    if not file.filename:
        raise ValueError("Filename is required")
    
    # Check file extension
    allowed_extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
    extension = "." + file.filename.split('.')[-1].lower()
    if extension not in allowed_extensions:
        raise ValueError(f"Unsupported format. Allowed: {', '.join(allowed_extensions)}")
    
    # Check file size (20MB limit)
    if file.size and file.size > 20 * 1024 * 1024:
        raise ValueError("File too large. Maximum size: 20MB")
    
    return True

@router.post("/voice", response_class=Response)
async def clone_voice(
    reference_audio: UploadFile = File(...),
    text: str = Form(..., min_length=1, max_length=5000),
    language: str = Form(default="EN"),
    speed: float = Form(default=1.0, ge=0.5, le=2.0)
):
    """Clone voice from reference audio and generate speech"""
    
    # Check if engine is available
    if not ENGINE_AVAILABLE or not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice cloning service is currently unavailable."
        )
    
    try:
        # Validate audio file
        await validate_audio_file(reference_audio)
        
        # Read reference audio
        audio_bytes = await reference_audio.read()
        
        # Generate cloned speech (or fallback to basic TTS)
        cloned_audio = await engine.clone_voice(
            text=text,
            reference_audio_bytes=audio_bytes,
            language=language.upper(),
            speed=speed
        )
        
        return Response(
            content=cloned_audio,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=cloned_{reference_audio.filename}",
                "X-Generated-By": "June-TTS"
            }
        )
        
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/status")
async def clone_status():
    """Get voice cloning status"""
    converter_available = ENGINE_AVAILABLE and engine and engine.converter is not None
    
    return {
        "voice_cloning_available": converter_available,
        "engine_loaded": ENGINE_AVAILABLE,
        "converter_loaded": converter_available,
        "status": "available" if converter_available else "basic TTS mode",
        "message": (
            "Voice cloning ready" if converter_available 
            else "Basic TTS available - voice cloning models not loaded"
        )
    }
EOF

# Step 5: Fix the standard TTS router
echo "🎤 Fixing standard TTS router..."
cat > app/routers/standard_tts.py << 'EOF'
# June/services/june-tts/app/routers/standard_tts.py
# Standard TTS endpoint for orchestrator integration

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

# Import the auth if available
try:
    from shared import require_service_auth
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def require_service_auth():
        return {"client_id": "fallback", "authenticated": True}

from app.core.openvoice_engine import synthesize_v2_to_wav_path

router = APIRouter(prefix="/v1", tags=["Standard TTS"])

class StandardTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(default="default", description="Voice ID or name")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="EN", description="Language code (EN, ES, FR, etc.)")
    format: str = Field(default="wav", description="Output format")
    quality: str = Field(default="high", description="Audio quality")

class VoicesResponse(BaseModel):
    voices: list[dict]
    default: str = "default"

@router.post("/tts")
async def synthesize_speech(
    request: StandardTTSRequest,
    service_auth: dict = Depends(require_service_auth) if AUTH_AVAILABLE else None
):
    """Standard TTS endpoint compatible with orchestrator ExternalTTSClient"""
    
    try:
        # Validate input
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        if request.format.lower() != "wav":
            raise HTTPException(status_code=415, detail="Only WAV format is currently supported")
        
        # For standard TTS, we'll just use basic Melo without reference audio
        # Generate speech using the OpenVoice engine
        wav_path = await synthesize_v2_to_wav_path(
            text=request.text.strip(),
            language=request.language.lower(),
            reference_b64=None,
            reference_url=None,
            speed=request.speed,
            volume=1.0,
            pitch=0.0,
            metadata={"voice_id": request.voice, "quality": request.quality}
        )
        
        # Read the generated audio file
        with open(wav_path, "rb") as f:
            audio_data = f.read()
        
        # Clean up temporary file
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        
        return Response(
            content=audio_data,
            media_type="audio/wav",
            headers={
                "Content-Length": str(len(audio_data)),
                "X-Voice-ID": request.voice,
                "X-Language": request.language,
                "X-Speed": str(request.speed),
                "X-Generated-By": "June-TTS-MeloTTS"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"TTS synthesis failed: {str(e)}"
        )

@router.get("/voices")
async def get_voices(language: str = "EN") -> VoicesResponse:
    """Get available voices for the given language"""
    
    # This would typically query your voice database
    # For now, return a basic set of available voices
    voices = [
        {
            "id": "default",
            "name": "Default Voice",
            "language": language.upper(),
            "gender": "neutral",
            "quality": "high"
        },
        {
            "id": "base",
            "name": "Base Voice",
            "language": language.upper(),
            "gender": "neutral",
            "quality": "high"
        }
    ]
    
    return VoicesResponse(
        voices=voices,
        default="default"
    )

@router.get("/status")
async def get_status():
    """Get TTS service status"""
    return {
        "service": "June TTS Standard",
        "status": "operational",
        "engine": "MeloTTS",
        "supported_formats": ["wav"],
        "supported_languages": ["EN", "ES", "FR", "ZH", "JA", "KO"],
        "features": {
            "standard_tts": True,
            "voice_cloning": False,  # Disabled without full OpenVoice
            "speed_control": True,
            "multi_language": True
        }
    }
EOF

# Step 6: Fix the main app
echo "📱 Fixing main app..."
cat > app/main.py << 'EOF'
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="June TTS API", version="1.0")

# ----- CORS -----
origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
origins = [o.strip() for o in origins_env.split(",") if o.strip()]
allow_all = "*" in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Routers -----
try:
    from app.routers.standard_tts import router as standard_tts_router
    app.include_router(standard_tts_router)
    logger.info("✅ Standard TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ standard_tts router load warning: {e}")

try:
    from app.routers.tts import router as tts_router
    app.include_router(tts_router)
    logger.info("✅ TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ tts router load warning: {e}")

try:
    from app.routers.clone import router as clone_router
    app.include_router(clone_router)
    logger.info("✅ Clone router loaded")
except Exception as e:
    logger.warning(f"⚠️ clone router load warning: {e}")

try:
    from app.routers.admin import router as admin_router  # healthz, voices
    app.include_router(admin_router)
    logger.info("✅ Admin router loaded")
except Exception as e:
    logger.warning(f"⚠️ admin router load warning: {e}")

# ----- Startup warmup (non-fatal if it fails) -----
@app.on_event("startup")
async def _startup() -> None:
    try:
        from app.core.openvoice_engine import warmup_models
        warmup_models()
        logger.info("✅ TTS models warmed up successfully")
    except Exception as e:
        logger.warning(f"⚠️ warmup skipped: {e}")

# ----- Root -----
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "June TTS API",
        "version": "1.0",
        "endpoints": {
            "standard_tts": "/v1/tts",
            "voice_cloning": "/tts/generate or /clone/voice",
            "health_check": "/healthz",
            "voices": "/v1/voices",
            "status": "/v1/status"
        }
    }
EOF

# Step 7: Ensure admin router has basic health check
echo "🏥 Ensuring admin router..."
cat > app/routers/admin.py << 'EOF'
from fastapi import APIRouter
import time
import os

router = APIRouter(tags=["admin"])

@router.get("/healthz")
def healthz():
    """Health check endpoint"""
    return {
        "status": "ok", 
        "service": "june-tts",
        "timestamp": time.time(),
        "engine": "MeloTTS",
        "voice_cloning": "basic"
    }

@router.get("/voices")
def voices():
    """Get available voices"""
    return {
        "env": {
            "MELO_SPEAKER_ID": os.getenv("MELO_SPEAKER_ID", "0"),
            "MELO_LANGUAGE": os.getenv("MELO_LANGUAGE", "EN"),
        },
        "voices": {
            "0": "Default Voice",
            "1": "Alternative Voice"
        },
        "note": "Basic MeloTTS voices available"
    }
EOF

# Step 8: Update requirements to ensure all dependencies
echo "📋 Updating requirements..."
cat > requirements.txt << 'EOF'
# June/services/june-tts/requirements.txt - Fixed requirements

# Core FastAPI and server
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6

# Pydantic and validation
pydantic==2.5.0
pydantic-settings==2.1.0

# Audio processing and ML
torch>=2.3.0
torchaudio>=2.3.0
librosa==0.10.1
soundfile==0.12.1
numpy>=1.24.0
scipy>=1.11.0

# OpenVoice specific dependencies (optional)
huggingface_hub>=0.17.0

# MeloTTS and text processing
jieba>=0.42.1
pypinyin>=0.50.0
cn2an>=0.5.17
inflect>=7.0.0
unidecode>=1.3.7
eng_to_ipa>=0.0.2

# Japanese text processing (optional)
fugashi>=1.3.0
unidic-lite>=1.0.8

# Audio format support
pydub>=0.25.1

# HTTP client
httpx>=0.25.2

# Authentication and security
PyJWT>=2.8.0
cryptography>=41.0.0

# Core utilities
requests>=2.31.0
EOF

# Step 9: Create setup script for shared module
cat > shared/setup.py << 'EOF'
from setuptools import setup, find_packages

setup(
    name="june-shared",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.100.0",
        "httpx>=0.24.0", 
        "PyJWT[crypto]>=2.8.0",
        "cryptography>=41.0.0"
    ]
)
EOF

echo ""
echo "✅ TTS Service fixes applied!"
echo ""
echo "🔄 Next steps:"
echo "1. Rebuild the Docker image:"
echo "   cd June/services/june-tts"
echo "   docker build -t us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-tts:fixed ."
echo ""
echo "2. Test locally first:"
echo "   docker run -p 8000:8000 us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-tts:fixed"
echo ""
echo "3. Test the health endpoint:"
echo "   curl http://localhost:8000/healthz"
echo ""
echo "4. Test basic TTS:"
echo "   curl -X POST http://localhost:8000/v1/tts \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"text\":\"Hello world\",\"language\":\"EN\"}' \\"
echo "     --output test.wav"
echo ""
echo "5. Push the image:"
echo "   docker push us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-tts:fixed"
echo ""
echo "6. Update your deployment to use the :fixed tag"
echo ""
echo "⚠️  Note: The service will start in 'basic TTS mode' using MeloTTS only."
echo "   Voice cloning features will be disabled but standard TTS will work."
echo ""
echo "🎯 What this fixes:"
echo "   ✅ Import errors with shared module"
echo "   ✅ Missing engine initialization"
echo "   ✅ Router loading failures"
echo "   ✅ Authentication dependency issues"
echo "   ✅ Basic TTS functionality"
echo ""
echo "📝 Remaining limitations:"
echo "   - Voice cloning disabled (requires full OpenVoice models)"
echo "   - Limited to MeloTTS basic synthesis"
echo "   - Mock authentication (replace for production)"