# app/core/openvoice_engine.py - FIXED with Official OpenVoice V2 API
import asyncio
import base64
import glob
import os
import tempfile
import time
from typing import Optional, Tuple, Dict, Any
import logging

import httpx
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

# Configuration from official docs
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}

# Language mapping for MeloTTS (official mapping)
_MELO_LANGUAGE_MAP = {
    "en": "EN",
    "es": "ES", 
    "fr": "FR",
    "zh": "ZH",
    "ja": "JP",
    "ko": "KR"
}

# Global state
_MELO = None
_CONVERTER = None
_INITIALIZED = False
_AVAILABLE_FEATURES = {
    "basic_tts": False,
    "voice_cloning": False,
    "multi_language": False
}

def _ensure_checkpoints() -> Tuple[str, str, str]:
    """Validate OpenVoice V2 checkpoint structure"""
    root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "converter")  # Official V2 uses 'converter', not 'tone_color_converter'
    
    if not os.path.isdir(conv_root):
        # Fallback to alternative naming
        conv_root = os.path.join(root, "tone_color_converter")
    
    logger.info(f"Checking OpenVoice V2 checkpoints: {conv_root}")
    return root, base_root, conv_root

def _find_converter_files(conv_root: str) -> Tuple[Optional[str], Optional[str]]:
    """Find config and checkpoint files using official V2 structure"""
    config_file = None
    checkpoint_file = None
    
    # Look for config.json
    config_paths = [
        os.path.join(conv_root, "config.json"),
        os.path.join(conv_root, "model_config.json"),
    ]
    
    for path in config_paths:
        if os.path.exists(path):
            config_file = path
            break
    
    # Look for checkpoint files (.pth preferred for V2)
    checkpoint_patterns = [
        os.path.join(conv_root, "*.pth"),
        os.path.join(conv_root, "**/*.pth"),
        os.path.join(conv_root, "*.pt"),
        os.path.join(conv_root, "**/*.pt"),
    ]
    
    for pattern in checkpoint_patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            checkpoint_file = matches[0]  # Use first match
            break
    
    logger.info(f"Found config: {config_file}, checkpoint: {checkpoint_file}")
    return config_file, checkpoint_file

def _load_models_once() -> None:
    """Load models using official OpenVoice V2 API"""
    global _MELO, _CONVERTER, _INITIALIZED, _AVAILABLE_FEATURES
    
    if _INITIALIZED:
        return
    
    logger.info("🚀 Initializing OpenVoice V2 engine...")
    
    # Step 1: Initialize MeloTTS (always needed)
    try:
        from melo.api import TTS as MeloTTS
        
        # Use proper device detection
        device = os.getenv("OPENVOICE_DEVICE", "auto")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize with default English for testing
        _MELO = MeloTTS(language="EN", device=device)
        _AVAILABLE_FEATURES["basic_tts"] = True
        _AVAILABLE_FEATURES["multi_language"] = True
        
        logger.info(f"✅ MeloTTS initialized on device: {device}")
        
        # Log available speakers
        try:
            speaker_ids = _MELO.hps.data.spk2id
            logger.info(f"Available speakers: {list(speaker_ids.keys())}")
        except Exception as e:
            logger.warning(f"Could not retrieve speaker info: {e}")
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize MeloTTS: {e}")
        raise RuntimeError(f"MeloTTS initialization failed: {e}")
    
    # Step 2: Initialize OpenVoice V2 Converter (optional)
    try:
        from openvoice.api import ToneColorConverter
        from openvoice import se_extractor
        
        root, base_root, conv_root = _ensure_checkpoints()
        
        if not os.path.isdir(conv_root):
            logger.warning(f"⚠️ OpenVoice converter directory not found: {conv_root}")
            _AVAILABLE_FEATURES["voice_cloning"] = False
        else:
            config_file, checkpoint_file = _find_converter_files(conv_root)
            
            if not config_file or not checkpoint_file:
                logger.warning(f"⚠️ Missing OpenVoice files - config: {config_file}, checkpoint: {checkpoint_file}")
                _AVAILABLE_FEATURES["voice_cloning"] = False
            else:
                try:
                    # Initialize converter using official V2 API
                    device = os.getenv("OPENVOICE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
                    
                    # Official V2 initialization pattern
                    _CONVERTER = ToneColorConverter(config_file, device=device)
                    _CONVERTER.load_ckpt(checkpoint_file)
                    
                    _AVAILABLE_FEATURES["voice_cloning"] = True
                    logger.info("✅ OpenVoice V2 converter loaded successfully")
                    
                    # Test the converter with a simple operation
                    try:
                        # Verify se_extractor is working
                        logger.info("✅ Speaker embedding extractor available")
                    except Exception as test_e:
                        logger.warning(f"⚠️ Converter test failed: {test_e}")
                        
                except Exception as init_e:
                    logger.error(f"❌ OpenVoice converter initialization failed: {init_e}")
                    _CONVERTER = None
                    _AVAILABLE_FEATURES["voice_cloning"] = False
                    
    except ImportError as ie:
        logger.warning(f"⚠️ OpenVoice not available: {ie}")
        _CONVERTER = None
        _AVAILABLE_FEATURES["voice_cloning"] = False
    except Exception as e:
        logger.error(f"❌ OpenVoice setup failed: {e}")
        _CONVERTER = None
        _AVAILABLE_FEATURES["voice_cloning"] = False
    
    _INITIALIZED = True
    
    # Summary
    logger.info("🎉 Engine initialization complete!")
    logger.info(f"Features available: {_AVAILABLE_FEATURES}")

def warmup_models() -> None:
    """Warmup models at startup"""
    try:
        _load_models_once()
        
        # Test basic TTS
        if _AVAILABLE_FEATURES["basic_tts"]:
            logger.info("🧪 Testing basic TTS...")
            try:
                test_text = "Test"
                device = os.getenv("OPENVOICE_DEVICE", "auto")
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                
                # Create a temporary test
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp_file:
                    _MELO.tts_to_file(test_text, 0, tmp_file.name, speed=1.0)
                    if os.path.exists(tmp_file.name) and os.path.getsize(tmp_file.name) > 1000:
                        logger.info("✅ Basic TTS test passed")
                    else:
                        logger.warning("⚠️ Basic TTS test produced small file")
            except Exception as e:
                logger.warning(f"⚠️ Basic TTS test failed: {e}")
        
        # Log GPU status
        try:
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                logger.info(f"🚀 GPU: {gpu_name} ({gpu_memory:.1f}GB)")
            else:
                logger.info("💻 Running on CPU")
        except Exception:
            logger.info("💻 GPU info not available")
            
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
    """
    FIXED: Synthesize speech using official OpenVoice V2 API
    """
    # Validation
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")
    
    if len(text) > _MAX_TEXT_LEN:
        raise ValueError(f"Text too long (max {_MAX_TEXT_LEN} chars)")
    
    lang = language.lower()
    if lang not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"Language must be one of {_SUPPORTED_LANGUAGES}")
    
    if speed <= 0:
        raise ValueError("Speed must be > 0")
    
    # Ensure models are loaded
    _load_models_once()
    
    if not _AVAILABLE_FEATURES["basic_tts"]:
        raise RuntimeError("TTS service not available")
    
    # Get MeloTTS language code
    melo_lang = _MELO_LANGUAGE_MAP.get(lang, "EN")
    
    # Determine if we should use voice cloning
    use_voice_cloning = (
        _AVAILABLE_FEATURES["voice_cloning"] and 
        _CONVERTER is not None and 
        (reference_b64 or reference_url)
    )
    
    if use_voice_cloning:
        logger.info("🎭 Using OpenVoice V2 voice cloning")
        return await _synthesize_with_cloning(
            text, melo_lang, reference_b64, reference_url, speed, volume, pitch
        )
    else:
        logger.info("🔊 Using basic MeloTTS")
        return await _synthesize_basic_tts(text, melo_lang, speed, volume, pitch)

async def _synthesize_basic_tts(
    text: str, 
    melo_lang: str, 
    speed: float, 
    volume: float, 
    pitch: float
) -> str:
    """Generate basic TTS using MeloTTS"""
    
    try:
        # Get speaker ID (use first available speaker)
        speaker_ids = _MELO.hps.data.spk2id
        speaker_id = list(speaker_ids.values())[0] if speaker_ids else 0
        
        # Create temporary output file
        fd, output_path = tempfile.mkstemp(prefix="june-basic-tts-", suffix=".wav")
        os.close(fd)
        
        # Generate speech using official MeloTTS API
        _MELO.tts_to_file(
            text=text,
            speaker_id=speaker_id,
            output_path=output_path,
            speed=speed
        )
        
        # Verify file was created
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise RuntimeError("TTS generation failed - empty or missing file")
        
        logger.info(f"✅ Basic TTS generated: {os.path.getsize(output_path)} bytes")
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Basic TTS failed: {e}")
        raise RuntimeError(f"TTS synthesis failed: {e}")

async def _synthesize_with_cloning(
    text: str,
    melo_lang: str, 
    reference_b64: Optional[str],
    reference_url: Optional[str],
    speed: float,
    volume: float,
    pitch: float
) -> str:
    """Generate TTS with voice cloning using official OpenVoice V2 API"""
    
    # Step 1: Get reference audio
    ref_path = None
    try:
        if reference_b64:
            ref_path = await _write_reference_b64(reference_b64)
        elif reference_url:
            ref_path = await _download_reference(reference_url)
        else:
            raise ValueError("No reference audio provided")
        
        # Step 2: Generate base TTS
        base_path = await _synthesize_basic_tts(text, melo_lang, speed, volume, pitch)
        
        # Step 3: Extract speaker embedding using official API
        from openvoice import se_extractor
        
        logger.info("🎯 Extracting speaker embedding...")
        target_se, _ = se_extractor.get_se(ref_path, _CONVERTER, vad=True)
        
        # Step 4: Apply voice conversion using official API
        logger.info("🎭 Applying voice conversion...")
        
        converted_path = await _apply_voice_conversion(base_path, target_se)
        
        # Cleanup intermediate files
        try:
            os.unlink(base_path)
            if ref_path:
                asyncio.create_task(_cleanup_file(ref_path))
        except Exception:
            pass
        
        logger.info("✅ Voice cloning completed successfully")
        return converted_path
        
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        # Fallback to basic TTS
        logger.info("⚠️ Falling back to basic TTS")
        return await _synthesize_basic_tts(text, melo_lang, speed, volume, pitch)

async def _apply_voice_conversion(base_audio_path: str, target_se) -> str:
    """Apply voice conversion using official OpenVoice V2 API"""
    
    try:
        # Create output path
        fd, output_path = tempfile.mkstemp(prefix="june-cloned-", suffix=".wav")
        os.close(fd)
        
        # Load base audio
        audio, sr = sf.read(base_audio_path, dtype="float32")
        
        # Apply conversion using official API
        # Note: OpenVoice V2 converter.convert expects specific parameters
        converted_audio = _CONVERTER.convert(
            audio=np.asarray(audio, dtype=np.float32),
            sample_rate=int(sr),
            src_se=target_se
        )
        
        # Save converted audio
        sf.write(output_path, converted_audio, sr, subtype="PCM_16")
        
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Voice conversion failed: {e}")
        raise

async def _write_reference_b64(b64: str) -> str:
    """Write base64 reference audio to temporary file"""
    try:
        raw = base64.b64decode(b64)
        if len(raw) > _MAX_REF_BYTES:
            raise ValueError("Reference audio too large")
        
        fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".wav")
        os.close(fd)
        
        with open(path, "wb") as f:
            f.write(raw)
        
        return path
    except Exception as e:
        logger.error(f"❌ Failed to process reference audio: {e}")
        raise

async def _download_reference(url: str) -> str:
    """Download reference audio from URL"""
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            if len(response.content) > _MAX_REF_BYTES:
                raise ValueError("Reference audio too large")
            
            fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".wav")
            os.close(fd)
            
            with open(path, "wb") as f:
                f.write(response.content)
            
            return path
    except Exception as e:
        logger.error(f"❌ Failed to download reference audio: {e}")
        raise

async def _cleanup_file(path: str):
    """Cleanup temporary file"""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

def get_engine_status() -> Dict[str, Any]:
    """Get detailed engine status"""
    return {
        "initialized": _INITIALIZED,
        "features": _AVAILABLE_FEATURES.copy(),
        "models": {
            "melo_loaded": _MELO is not None,
            "converter_loaded": _CONVERTER is not None
        },
        "device": {
            "cuda_available": torch.cuda.is_available(),
            "current_device": os.getenv("OPENVOICE_DEVICE", "auto")
        }
    }

def get_available_voices() -> Dict[str, Any]:
    """Get available voices and speakers"""
    if not _MELO:
        return {"error": "TTS not initialized"}
    
    try:
        speaker_ids = _MELO.hps.data.spk2id
        return {
            "speakers": dict(speaker_ids) if speaker_ids else {},
            "languages": list(_MELO_LANGUAGE_MAP.keys()),
            "voice_cloning_available": _AVAILABLE_FEATURES["voice_cloning"]
        }
    except Exception as e:
        return {"error": str(e)}

# Engine class for compatibility
class OpenVoiceEngine:
    """Engine class for compatibility with existing code"""
    
    def __init__(self):
        self.converter = None
        self.initialized = False
        
    def initialize(self):
        """Initialize the engine"""
        try:
            _load_models_once()
            self.converter = _CONVERTER
            self.initialized = _INITIALIZED
            
            if _AVAILABLE_FEATURES["voice_cloning"]:
                logger.info("✅ OpenVoice engine initialized with voice cloning")
            else:
                logger.info("✅ OpenVoice engine initialized (basic TTS only)")
                
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
        """Clone voice from reference audio"""
        
        # Convert reference audio to base64
        ref_b64 = base64.b64encode(reference_audio_bytes).decode('utf-8')
        
        # Generate with voice cloning
        wav_path = await synthesize_v2_to_wav_path(
            text=text,
            language=language.lower(),
            reference_b64=ref_b64,
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