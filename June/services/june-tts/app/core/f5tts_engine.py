"""
F5-TTS Engine for June TTS Service
State-of-the-art voice cloning with multilingual support
"""

import io
import tempfile
import os
from typing import Optional
import torch
import soundfile as sf
import numpy as np
from f5_tts.api import F5TTS
from f5_tts.model import DiT, UNetT
from f5_tts.infer.utils_infer import (
    load_model,
    infer_process,
    remove_silence_for_generated_wav
)

from .config import settings

# Global F5-TTS instance
_f5tts: Optional[F5TTS] = None

def _load_model() -> F5TTS:
    """Load F5-TTS model"""
    global _f5tts
    
    if _f5tts is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize F5-TTS
        _f5tts = F5TTS(
            model_type="F5-TTS",  # or "E2-TTS" for faster inference
            ckpt_file="",  # Uses default pretrained model
            vocab_file="",  # Uses default vocab
            ode_method="euler",  # Sampling method
            use_ema=True,
            device=device
        )
        
        print(f"✅ F5-TTS loaded on {device}")
    
    return _f5tts

def _audio_to_bytes(audio_array: np.ndarray, sample_rate: int = 24000) -> bytes:
    """Convert audio array to WAV bytes"""
    buf = io.BytesIO()
    sf.write(buf, audio_array, samplerate=sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()

async def synthesize_tts(
    text: str,
    language: str = "en",
    speed: float = 1.0,
    speaker_wav: Optional[str] = None
) -> bytes:
    """
    Standard TTS synthesis using F5-TTS default voice
    """
    f5tts = _load_model()
    
    try:
        # Generate audio with F5-TTS
        # For basic TTS without reference audio, use default speaker
        audio_array, sample_rate = f5tts.infer(
            text=text,
            ref_audio=None,  # No reference for standard TTS
            ref_text="",     # No reference text needed
            speed=speed
        )
        
        # Remove silence and normalize
        audio_array = remove_silence_for_generated_wav(audio_array)
        
        return _audio_to_bytes(audio_array, sample_rate)
    
    except Exception as e:
        print(f"F5-TTS synthesis error: {e}")
        raise

async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "en",
    speed: float = 1.0,
    reference_text: str = ""
) -> bytes:
    """
    Voice cloning with F5-TTS
    
    Args:
        text: Text to synthesize
        reference_audio_bytes: Reference audio for voice cloning
        language: Language (F5-TTS is multilingual by default)
        speed: Speech speed
        reference_text: Optional transcription of reference audio (improves quality)
    """
    f5tts = _load_model()
    
    # Save reference audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
        ref_path = ref_file.name
        ref_file.write(reference_audio_bytes)
    
    try:
        # Load reference audio
        ref_audio, ref_sr = sf.read(ref_path)
        
        # If no reference text provided, use a default
        if not reference_text.strip():
            reference_text = "This is a reference audio for voice cloning."
        
        # Generate cloned audio
        audio_array, sample_rate = f5tts.infer(
            text=text,
            ref_audio=ref_audio,
            ref_text=reference_text,
            speed=speed,
            cross_fade_duration=0.15  # Smooth transitions
        )
        
        # Post-process: remove silence
        audio_array = remove_silence_for_generated_wav(audio_array)
        
        return _audio_to_bytes(audio_array, sample_rate)
    
    finally:
        # Cleanup temp file
        if os.path.exists(ref_path):
            os.unlink(ref_path)

def warmup_models() -> None:
    """Load models at startup"""
    try:
        _load_model()
        print("✅ F5-TTS models warmed up successfully")
    except Exception as e:
        print(f"⚠️ F5-TTS warmup failed: {e}")

def get_supported_languages() -> list[str]:
    """F5-TTS supported languages (multilingual model)"""
    return [
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", 
        "zh-cn", "zh-tw", "ja", "ko", "hi", "th", "vi", "id", "ms", "tl", "sw",
        "bn", "ur", "te", "ta", "ml", "kn", "gu", "pa", "mr", "ne", "si", "my",
        "km", "lo", "ka", "am", "is", "mt", "cy", "eu", "ca", "gl", "ast", "an",
        "oc", "br", "co", "bo", "dv", "fo", "fy", "gd", "ga", "gn", "gu", "ha",
        "haw", "he", "ig", "jw", "kk", "ky", "lb", "ln", "mg", "mi", "mk", "mn",
        "ps", "qu", "rw", "sd", "sn", "so", "su", "sv", "tg", "tk", "tt", "ug",
        "uz", "wo", "xh", "yi", "yo", "zu"
    ]

def get_available_speakers() -> dict:
    """F5-TTS uses reference audio for voice cloning"""
    return {
        "message": "F5-TTS uses reference audio for zero-shot voice cloning",
        "supported_languages": get_supported_languages(),
        "voice_cloning": "Upload reference audio (3-30 seconds recommended)",
        "reference_text": "Providing transcription of reference audio improves quality"
    }
