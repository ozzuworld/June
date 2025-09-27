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
        from openvoice.api import ToneColorConverter
        from openvoice import se_extractor
        
        # Initialize Melo (always needed)
        _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))
        _SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "0")
        logger.info("✅ MeloTTS loaded successfully")
        
        # Try to initialize converter (optional)
        try:
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
                
        except Exception as e:
            logger.warning(f"⚠️ Could not load voice converter: {e}")
            _CONVERTER = None
        
    except Exception as e:
        logger.error(f"❌ Failed to load OpenVoice models: {e}")
        raise RuntimeError(f"OpenVoice initialization failed: {e}")

def warmup_models() -> None:
    """Warmup models at startup"""
    try:
        _load_models_once()
        logger.info("✅ OpenVoice models warmed up successfully")
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
    spk = int(os.getenv("MELO_SPEAKER_ID", "0"))
    
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
        raise RuntimeError("Unsupported MeloTTS build")

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
