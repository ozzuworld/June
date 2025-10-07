"""
F5-TTS Engine for June TTS Service
State-of-the-art TTS with voice cloning using official F5-TTS
"""

import io
import tempfile
import os
import logging
from typing import Optional, List
import torch
import soundfile as sf
import numpy as np

# F5-TTS imports
from f5_tts.infer.utils_infer import (
    infer_process,
    load_vocoder,
    load_model,
    preprocess_ref_audio_text,
    remove_silence_for_generated_wav
)
from f5_tts.model import DiT, UNetT

logger = logging.getLogger(__name__)

# Global model instances
_f5tts_model = None
_vocoder = None
_device = None

# Model configurations
F5TTS_model_cfg = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
E2TTS_model_cfg = dict(dim=1024, depth=24, heads=16, ff_mult=4)

def _get_device():
    """Get the best available device"""
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    else:
        return "cpu"

def _load_models():
    """Load F5-TTS models"""
    global _f5tts_model, _vocoder, _device
    
    if _f5tts_model is None:
        _device = _get_device()
        logger.info(f"🔄 Loading F5-TTS on {_device}")
        
        try:
            # Load F5-TTS model
            ckpt_file = "hf://SWivid/F5-TTS/F5TTS_Base/model_1200000.safetensors"
            vocab_file = "hf://SWivid/F5-TTS/F5TTS_Base/vocab.txt"
            
            _f5tts_model = load_model(
                DiT, 
                F5TTS_model_cfg, 
                ckpt_file, 
                vocab_file, 
                ode_method="euler", 
                use_ema=True,
                device=_device
            )
            
            # Load vocoder
            _vocoder = load_vocoder(device=_device)
            
            logger.info("✅ F5-TTS models loaded successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to load F5-TTS models: {e}")
            raise RuntimeError(f"Could not load F5-TTS: {e}")
    
    return _f5tts_model, _vocoder

async def synthesize_tts(
    text: str,
    language: str = "en",
    speed: float = 1.0,
    **kwargs
) -> bytes:
    """
    Standard TTS synthesis using F5-TTS
    """
    try:
        model, vocoder = _load_models()
        
        logger.info(f"🔊 Synthesizing: {text[:50]}...")
        
        # For basic TTS, we use a default reference
        # In production, you might want to have a library of reference voices
        ref_audio_orig = torch.zeros(24000 * 3).unsqueeze(0)  # 3 seconds of silence
        ref_text = "This is a clear reference voice for text to speech synthesis."
        
        # Preprocess
        ref_audio, ref_text = preprocess_ref_audio_text(ref_audio_orig, ref_text, device=_device)
        
        # Generate audio
        final_wave, final_sample_rate, combined_spectrogram = infer_process(
            ref_audio=ref_audio,
            ref_text=ref_text,
            gen_text=text,
            model_obj=model,
            vocoder=vocoder,
            mel_spec_type="vocos",
            speed=speed,
            device=_device
        )
        
        # Post-process
        final_wave = remove_silence_for_generated_wav(final_wave)
        
        # Convert to bytes
        return _audio_to_bytes(final_wave, final_sample_rate)
        
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
    Voice cloning with F5-TTS
    """
    try:
        model, vocoder = _load_models()
        
        # Save reference audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
            ref_path = ref_file.name
            ref_file.write(reference_audio_bytes)
        
        try:
            # Load reference audio
            ref_audio_orig, sr = sf.read(ref_path)
            ref_audio_orig = torch.FloatTensor(ref_audio_orig)
            
            # Use provided reference text or default
            if not reference_text.strip():
                reference_text = "This is the reference audio for voice cloning."
            
            logger.info(f"🔊 Cloning voice: {text[:50]}...")
            
            # Preprocess
            ref_audio, ref_text = preprocess_ref_audio_text(
                ref_audio_orig, reference_text, device=_device
            )
            
            # Generate cloned audio
            final_wave, final_sample_rate, combined_spectrogram = infer_process(
                ref_audio=ref_audio,
                ref_text=ref_text,
                gen_text=text,
                model_obj=model,
                vocoder=vocoder,
                mel_spec_type="vocos",
                speed=speed,
                device=_device
            )
            
            # Post-process
            final_wave = remove_silence_for_generated_wav(final_wave)
            
            return _audio_to_bytes(final_wave, final_sample_rate)
            
        finally:
            # Cleanup
            if os.path.exists(ref_path):
                os.unlink(ref_path)
                
    except Exception as e:
        logger.error(f"❌ F5-TTS voice cloning error: {e}")
        raise

def _audio_to_bytes(audio_array: np.ndarray, sample_rate: int = 24000) -> bytes:
    """Convert audio array to WAV bytes"""
    buf = io.BytesIO()
    sf.write(buf, audio_array, samplerate=sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()

def warmup_models() -> None:
    """Load models at startup"""
    try:
        _load_models()
        logger.info("✅ F5-TTS models warmed up successfully")
    except Exception as e:
        logger.error(f"⚠️ F5-TTS warmup failed: {e}")
        raise

def get_supported_languages() -> List[str]:
    """F5-TTS supported languages"""
    return [
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", 
        "zh-cn", "zh-tw", "ja", "ko", "hi", "th", "vi", "id", "ms", "tl"
    ]

def get_available_speakers() -> dict:
    """F5-TTS capabilities"""
    return {
        "message": "F5-TTS: State-of-the-art voice cloning with flow matching",
        "engine": "F5-TTS v1.1.9",
        "voice_cloning": "Zero-shot voice cloning with reference audio",
        "supported_languages": get_supported_languages(),
        "features": {
            "zero_shot_cloning": True,
            "multilingual": True,
            "real_time": True,
            "high_quality": True
        },
        "recommendations": {
            "ref_audio_length": "3-15 seconds",
            "ref_audio_quality": "Clear speech, minimal noise",
            "ref_text_accuracy": "Accurate transcription improves quality",
            "supported_formats": ["wav", "mp3", "flac", "m4a"]
        }
    }
