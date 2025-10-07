"""
F5-TTS Engine - Following Official F5-TTS Documentation
Simple implementation using the official F5TTS API class
"""

import io
import tempfile
import os
import logging
from typing import Optional, List
import soundfile as sf

# Official F5-TTS import (as per documentation)
from f5_tts.api import F5TTS

logger = logging.getLogger(__name__)

# Global F5TTS instance
_f5tts: Optional[F5TTS] = None

def _get_model() -> F5TTS:
    """Get F5TTS model instance (official API)"""
    global _f5tts
    
    if _f5tts is None:
        logger.info("🔄 Loading F5-TTS using official API")
        try:
            # Official F5TTS initialization (from vendor docs)
            _f5tts = F5TTS()
            logger.info("✅ F5-TTS loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load F5-TTS: {e}")
            raise RuntimeError(f"Could not load F5-TTS: {e}")
    
    return _f5tts

async def synthesize_tts(
    text: str,
    language: str = "en",
    speed: float = 1.0,
    **kwargs
) -> bytes:
    """
    Standard TTS synthesis using F5-TTS official API
    """
    try:
        model = _get_model()
        
        logger.info(f"🔊 Synthesizing: {text[:50]}...")
        
        # Use F5TTS official API method
        # For basic TTS, F5-TTS still needs reference audio
        # Using the built-in example reference
        wav, sr, spect = model.infer(
            gen_text=text,
            # F5-TTS will use default reference if not provided
            speed=speed
        )
        
        # Convert to bytes
        return _audio_to_bytes(wav, sr)
        
    except Exception as e:
        logger.error(f"❌ F5-TTS synthesis error: {e}")
        raise

async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "en",
    speed: float = 1.0,
    reference_text: str = ""
) -> bytes:
    """
    Voice cloning with F5-TTS official API
    """
    try:
        model = _get_model()
        
        # Save reference audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
            ref_path = ref_file.name
            ref_file.write(reference_audio_bytes)
        
        try:
            # Use default reference text if none provided
            if not reference_text.strip():
                reference_text = "This is a reference audio for voice cloning."
            
            logger.info(f"🎭 Cloning voice: {text[:50]}...")
            
            # F5TTS official API for voice cloning
            wav, sr, spect = model.infer(
                ref_file=ref_path,
                ref_text=reference_text,
                gen_text=text,
                speed=speed
            )
            
            return _audio_to_bytes(wav, sr)
            
        finally:
            # Cleanup temp file
            if os.path.exists(ref_path):
                os.unlink(ref_path)
                
    except Exception as e:
        logger.error(f"❌ F5-TTS voice cloning error: {e}")
        raise

def _audio_to_bytes(audio_array, sample_rate: int) -> bytes:
    """Convert audio array to WAV bytes"""
    buf = io.BytesIO()
    sf.write(buf, audio_array, samplerate=sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()

def warmup_models() -> None:
    """Load models at startup"""
    try:
        _get_model()
        logger.info("✅ F5-TTS models warmed up successfully")
    except Exception as e:
        logger.error(f"⚠️ F5-TTS warmup failed: {e}")
        raise

def get_supported_languages() -> List[str]:
    """F5-TTS supported languages"""
    return [
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", 
        "zh-cn", "zh-tw", "ja", "ko", "hi", "th", "vi", "id", "ms"
    ]

def get_available_speakers() -> dict:
    """F5-TTS capabilities"""
    return {
        "message": "F5-TTS: Official API implementation",
        "engine": "F5-TTS Official",
        "voice_cloning": "Zero-shot voice cloning with reference audio",
        "supported_languages": get_supported_languages(),
        "features": {
            "zero_shot_cloning": True,
            "multilingual": True,
            "official_api": True
        },
        "recommendations": {
            "ref_audio_length": "3-15 seconds",
            "ref_audio_quality": "Clear speech, minimal noise",
            "ref_text_accuracy": "Accurate transcription improves quality"
        }
    }
