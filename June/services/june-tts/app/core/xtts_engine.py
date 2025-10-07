"""
XTTS v2 Engine for June TTS Service
Much simpler than MeloTTS + OpenVoice combination
"""

import io
import tempfile
from typing import Optional
import torch
import soundfile as sf
from TTS.api import TTS

from .config import settings

# Global XTTS instance
_xtts: Optional[TTS] = None

def _load_model() -> TTS:
    """Load XTTS v2 model"""
    global _xtts
    
    if _xtts is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize XTTS v2 model
        _xtts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", 
                   progress_bar=False).to(device)
        
        print(f"✅ XTTS v2 loaded on {device}")
    
    return _xtts

def _to_wav_bytes(audio_path: str) -> bytes:
    """Convert audio file to WAV bytes"""
    with open(audio_path, 'rb') as f:
        return f.read()

async def synthesize_tts(
    text: str,
    language: str = "en", 
    speaker_wav: Optional[str] = None,
    speed: float = 1.0
) -> bytes:
    """
    Standard TTS synthesis (no voice cloning)
    Uses XTTS default speakers
    """
    xtts = _load_model()
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        output_path = tmp_file.name
    
    try:
        # Generate audio with XTTS
        xtts.tts_to_file(
            text=text,
            file_path=output_path,
            speaker_wav=speaker_wav,  # Can be None for default speaker
            language=language,
            split_sentences=True  # Better for long text
        )
        
        return _to_wav_bytes(output_path)
    
    finally:
        import os
        if os.path.exists(output_path):
            os.unlink(output_path)

async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "en",
    speed: float = 1.0
) -> bytes:
    """
    Voice cloning with XTTS v2
    Much simpler than MeloTTS + OpenVoice!
    """
    xtts = _load_model()
    
    # Save reference audio
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
        ref_path = ref_file.name
        ref_file.write(reference_audio_bytes)
    
    # Output file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
        output_path = output_file.name
    
    try:
        # XTTS voice cloning (one step!)
        xtts.tts_to_file(
            text=text,
            file_path=output_path,
            speaker_wav=ref_path,  # Reference audio for cloning
            language=language,
            split_sentences=True
        )
        
        return _to_wav_bytes(output_path)
    
    finally:
        import os
        for path in [ref_path, output_path]:
            if os.path.exists(path):
                os.unlink(path)

def warmup_models() -> None:
    """Load models at startup"""
    try:
        _load_model()
        print("✅ XTTS v2 models warmed up successfully")
    except Exception as e:
        print(f"⚠️ XTTS warmup failed: {e}")

def get_supported_languages() -> list[str]:
    """XTTS v2 supported languages"""
    return ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"]

def get_available_speakers() -> dict:
    """XTTS uses reference audio for speakers"""
    return {
        "message": "XTTS uses reference audio for voice cloning",
        "supported_languages": get_supported_languages(),
        "default_speakers": "Use reference audio for voice cloning"
    }
