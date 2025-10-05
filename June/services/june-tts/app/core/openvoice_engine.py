"""
OpenVoice V2 Engine - CORRECTED Implementation
Following official OpenVoice V2 guidelines and API
"""

import io
import os
import tempfile
from typing import Tuple, Optional

import numpy as np
import soundfile as sf
import torch

# Standard imports (ctranslate2 issue fixed via deployment config)
from melo.api import TTS as MeloTTS
from openvoice import se_extractor
from openvoice.api import ToneColorConverter

from .config import settings

# Global instances
_melo: Optional[MeloTTS] = None
_converter: Optional[ToneColorConverter] = None


def _get_checkpoint_path() -> str:
    """Get the tone color converter checkpoint path"""
    base_path = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
    converter_path = os.path.join(base_path, "tone_color_converter")
    
    # Find checkpoint file
    import glob
    ckpt_files = glob.glob(os.path.join(converter_path, "*.pth")) + \
                 glob.glob(os.path.join(converter_path, "*.pt"))
    
    if not ckpt_files:
        raise FileNotFoundError(f"No checkpoint files found in {converter_path}")
    
    return ckpt_files[0]


def _load_models() -> Tuple[MeloTTS, ToneColorConverter]:
    """Load MeloTTS and ToneColorConverter models"""
    global _melo, _converter
    
    if _melo is None:
        # Initialize MeloTTS with default English speaker
        default_language = os.getenv("MELO_LANGUAGE", "EN")
        _melo = MeloTTS(language=default_language)
        print(f"✅ MeloTTS initialized with language: {default_language}")
    
    if _converter is None:
        # Initialize ToneColorConverter
        ckpt_path = _get_checkpoint_path()
        config_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        _converter = ToneColorConverter(config_path=config_path, device=device)
        _converter.load_ckpt(ckpt_path)
        
        print(f"✅ ToneColorConverter loaded from {ckpt_path} on {device}")
    
    return _melo, _converter


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Convert audio array to WAV bytes"""
    buf = io.BytesIO()
    sf.write(buf, audio, samplerate=sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


async def synthesize_tts(
    text: str, 
    language: str = "EN", 
    speed: float = 1.0,
    speaker_id: int = 0
) -> bytes:
    """
    Synthesize speech using base MeloTTS model (no voice cloning)
    
    Args:
        text: Text to synthesize
        language: Language code (EN, ES, FR, ZH, JP, KR)
        speed: Speech speed multiplier (0.5-2.0)
        speaker_id: Speaker ID for MeloTTS
    
    Returns:
        WAV audio bytes
    """
    melo, _ = _load_models()
    
    # Generate to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        # Generate audio
        melo.tts_to_file(
            text=text,
            speaker_id=speaker_id,
            output_path=tmp_path,
            speed=speed
        )
        
        # Read the generated file
        audio_data, sample_rate = sf.read(tmp_path, dtype='float32')
        
        # Convert to bytes
        return _to_wav_bytes(audio_data, sample_rate)
    
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "EN",
    speed: float = 1.0,
    speaker_id: int = 0
) -> bytes:
    """
    Clone voice using OpenVoice V2 tone color conversion with VAD
    
    This follows the OpenVoice V2 workflow:
    1. Generate base audio with MeloTTS
    2. Extract speaker embedding from reference (uses faster-whisper VAD)
    3. Apply tone color conversion
    
    Args:
        text: Text to synthesize
        reference_audio_bytes: Reference audio (WAV format)
        language: Language code
        speed: Speech speed
        speaker_id: Base speaker ID
    
    Returns:
        WAV audio bytes with cloned voice
    """
    melo, converter = _load_models()
    
    # Save reference audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
        ref_path = ref_file.name
        ref_file.write(reference_audio_bytes)
    
    # Generate base audio with MeloTTS
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as base_file:
        base_path = base_file.name
    
    try:
        # Generate base audio
        melo.tts_to_file(
            text=text,
            speaker_id=speaker_id,
            output_path=base_path,
            speed=speed
        )
        
        # Extract speaker embedding from reference with VAD
        # vad=True enables Voice Activity Detection using faster-whisper
        src_se, _ = se_extractor.get_se(ref_path, converter, vad=True)
        
        # Load base audio
        base_audio, sample_rate = sf.read(base_path, dtype='float32')
        
        # Apply tone color conversion
        output_audio = converter.convert(
            audio_src=base_audio,
            src_se=src_se,
            tgt_se=src_se,
            tau=0.3  # Tone color strength (0-1)
        )
        
        # Convert to bytes
        return _to_wav_bytes(output_audio, sample_rate)
    
    finally:
        # Cleanup temp files
        for path in [ref_path, base_path]:
            if os.path.exists(path):
                os.unlink(path)


def warmup_models() -> None:
    """Load models at startup to avoid cold start"""
    try:
        _load_models()
        print("✅ OpenVoice V2 models warmed up successfully")
        print("✅ VAD (Voice Activity Detection) enabled via faster-whisper")
    except Exception as e:
        print(f"⚠️ Model warmup failed: {e}")
        print("   Models will load on first request")


def get_supported_languages() -> list[str]:
    """Get list of supported languages"""
    return ["EN", "ES", "FR", "ZH", "JP", "KR"]


def get_available_speakers(language: str = "EN") -> dict:
    """Get available speaker IDs for a language"""
    speakers = {
        "EN": ["EN-US", "EN-BR", "EN-INDIA", "EN-AU", "EN-Default"],
        "ES": ["ES"],
        "FR": ["FR"],
        "ZH": ["ZH"],
        "JP": ["JP"],
        "KR": ["KR"]
    }
    
    return {
        "language": language,
        "speakers": speakers.get(language.upper(), ["Default"])
    }