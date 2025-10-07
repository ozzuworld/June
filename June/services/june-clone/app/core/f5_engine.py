"""
F5-TTS Engine for Voice Cloning
Optimized for zero-shot voice cloning with reference audio
"""

import io
import tempfile
import os
import logging
from typing import Optional, List, Tuple
import soundfile as sf
import numpy as np

# F5-TTS imports
from f5_tts.api import F5TTS

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global F5TTS instance
_f5tts: Optional[F5TTS] = None

def _get_model() -> F5TTS:
    """Get or initialize F5TTS model instance"""
    global _f5tts
    
    if _f5tts is None:
        logger.info("🔄 Loading F5-TTS for voice cloning...")
        try:
            # Initialize F5TTS with optimal settings for voice cloning
            _f5tts = F5TTS()
            logger.info("✅ F5-TTS loaded successfully for voice cloning")
            
            # Log device info
            device = "cuda" if is_gpu_available() else "cpu"
            logger.info(f"🎯 F5-TTS running on: {device}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load F5-TTS: {e}")
            raise RuntimeError(f"Could not initialize F5-TTS: {e}")
    
    return _f5tts

def is_gpu_available() -> bool:
    """Check if GPU is available"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

def _validate_audio_data(audio_data: np.ndarray, sample_rate: int) -> Tuple[np.ndarray, int]:
    """Validate and preprocess audio data"""
    
    # Ensure audio is mono
    if len(audio_data.shape) > 1:
        audio_data = np.mean(audio_data, axis=1)
    
    # Check duration
    duration = len(audio_data) / sample_rate
    if duration < settings.MIN_AUDIO_DURATION:
        raise ValueError(f"Audio too short: {duration:.1f}s (minimum: {settings.MIN_AUDIO_DURATION}s)")
    
    if duration > settings.MAX_AUDIO_DURATION:
        logger.warning(f"Audio duration {duration:.1f}s exceeds recommended {settings.MAX_AUDIO_DURATION}s")
    
    # Normalize audio
    if np.max(np.abs(audio_data)) > 0:
        audio_data = audio_data / np.max(np.abs(audio_data)) * 0.8
    
    return audio_data, sample_rate

async def clone_voice(
    text: str,
    reference_audio_bytes: bytes,
    language: str = "en",
    speed: float = 1.0,
    reference_text: str = ""
) -> bytes:
    """
    Clone voice using F5-TTS with reference audio
    
    Args:
        text: Text to synthesize
        reference_audio_bytes: Reference audio file bytes
        language: Target language
        speed: Speech speed multiplier
        reference_text: Transcription of reference audio
    
    Returns:
        Synthesized audio as bytes
    """
    try:
        model = _get_model()
        
        # Use default reference text if not provided
        if not reference_text.strip():
            reference_text = settings.get_default_reference_text(language)
        
        logger.info(f"🎭 Cloning voice: '{text[:50]}...' (lang: {language}, speed: {speed}x)")
        logger.info(f"📝 Reference text: '{reference_text[:50]}...'")
        
        # Save reference audio to temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_ref:
            temp_ref_path = temp_ref.name
            temp_ref.write(reference_audio_bytes)
        
        try:
            # Validate reference audio
            try:
                ref_audio, ref_sr = sf.read(temp_ref_path)
                ref_audio, ref_sr = _validate_audio_data(ref_audio, ref_sr)
                
                # Re-save validated audio
                sf.write(temp_ref_path, ref_audio, ref_sr)
                logger.info(f"🎵 Reference audio: {len(ref_audio)/ref_sr:.1f}s @ {ref_sr}Hz")
                
            except Exception as e:
                logger.error(f"❌ Reference audio validation failed: {e}")
                raise ValueError(f"Invalid reference audio: {e}")
            
            # Perform voice cloning with F5-TTS
            logger.info("🔄 Generating cloned voice...")
            wav, sr, spect = model.infer(
                ref_file=temp_ref_path,
                ref_text=reference_text,
                gen_text=text,
                speed=speed
            )
            
            # Validate output
            if wav is None or len(wav) == 0:
                raise RuntimeError("F5-TTS returned empty audio")
            
            logger.info(f"✅ Voice cloning completed: {len(wav)/sr:.2f}s audio generated")
            
            # Convert to bytes
            return _audio_to_bytes(wav, sr)
            
        finally:
            # Cleanup temporary file
            if os.path.exists(temp_ref_path):
                os.unlink(temp_ref_path)
                
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise

def _audio_to_bytes(audio_array: np.ndarray, sample_rate: int) -> bytes:
    """Convert audio array to WAV bytes"""
    try:
        # Ensure audio is in correct format
        if audio_array.dtype != np.float32:
            audio_array = audio_array.astype(np.float32)
        
        # Normalize if needed
        if np.max(np.abs(audio_array)) > 1.0:
            audio_array = audio_array / np.max(np.abs(audio_array)) * 0.95
        
        # Convert to bytes
        buffer = io.BytesIO()
        sf.write(buffer, audio_array, samplerate=sample_rate, format="WAV", subtype="PCM_16")
        buffer.seek(0)
        
        return buffer.read()
        
    except Exception as e:
        logger.error(f"❌ Audio conversion failed: {e}")
        raise

def warmup_models() -> None:
    """Load and warmup F5-TTS models"""
    try:
        logger.info("🔥 Warming up F5-TTS models...")
        model = _get_model()
        
        # Create a minimal test to ensure everything works
        logger.info("🧪 Running warmup inference test...")
        
        # Generate a simple test tone for warmup
        sample_rate = 24000
        duration = 2.0
        t = np.linspace(0, duration, int(sample_rate * duration))
        test_audio = 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        
        # Save test audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            sf.write(temp_file.name, test_audio, sample_rate)
            temp_path = temp_file.name
        
        try:
            # Warmup inference
            wav, sr, spect = model.infer(
                ref_file=temp_path,
                ref_text="This is a warmup test",
                gen_text="Hello world",
                speed=1.0
            )
            
            logger.info("✅ F5-TTS warmup completed successfully")
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"⚠️ F5-TTS warmup failed: {e}")
        raise

def get_supported_languages() -> List[str]:
    """Get list of supported languages"""
    return settings.SUPPORTED_LANGUAGES.copy()

def get_available_speakers() -> dict:
    """Get voice cloning capabilities information"""
    return {
        "message": "F5-TTS Zero-Shot Voice Cloning",
        "engine": "F5-TTS Official v1.1.9",
        "service": "june-voice-cloning",
        "capabilities": {
            "zero_shot_cloning": True,
            "multilingual": True,
            "real_time": True,
            "high_quality": True
        },
        "supported_languages": get_supported_languages(),
        "requirements": {
            "reference_audio": {
                "duration": f"{settings.MIN_AUDIO_DURATION}-{settings.MAX_AUDIO_DURATION} seconds",
                "quality": "Clear speech, minimal background noise",
                "format": "WAV, MP3, M4A, FLAC supported",
                "size_limit": "50MB maximum"
            },
            "reference_text": {
                "description": "Accurate transcription of reference audio",
                "impact": "Improves voice cloning quality significantly",
                "optional": "Will use default text if not provided"
            }
        },
        "performance": {
            "typical_inference_time": "1-3 seconds",
            "gpu_accelerated": is_gpu_available(),
            "device": "cuda" if is_gpu_available() else "cpu"
        },
        "usage_tips": [
            "Use 3-15 second clear speech samples",
            "Provide accurate transcription for best results",
            "Minimize background noise in reference audio",
            "Single speaker reference audio works best"
        ]
    }
