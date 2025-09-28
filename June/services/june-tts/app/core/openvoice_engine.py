# app/core/openvoice_engine.py - Enhanced with OpenVoice V2 support
import asyncio
import base64
import glob
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
    """Load models with comprehensive error handling and OpenVoice V2 support"""
    global _MELO, _CONVERTER, _SPEAKER_ID, _CONVERT_FN
    if _MELO is not None:
        return

    try:
        from melo.api import TTS as MeloTTS
        
        # Initialize Melo (always needed)
        _MELO = MeloTTS(language=os.getenv("MELO_LANGUAGE", "EN"))
        _SPEAKER_ID = os.getenv("MELO_SPEAKER_ID", "0")
        logger.info("✅ MeloTTS loaded successfully")
        
        # Try to initialize OpenVoice V2 converter
        try:
            from openvoice.api import ToneColorConverter
            from openvoice import se_extractor
            
            root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
            conv_root = os.path.join(root, "tone_color_converter")
            
            logger.info(f"🔍 Looking for OpenVoice models in: {conv_root}")
            
            if os.path.isdir(conv_root):
                cfg_path = os.path.join(conv_root, "config.json")
                
                # Look for checkpoint files more comprehensively
                ckpt_patterns = [
                    os.path.join(conv_root, "*.pth"),
                    os.path.join(conv_root, "*.pt"),
                    os.path.join(conv_root, "**", "*.pth"),
                    os.path.join(conv_root, "**", "*.pt"),
                ]
                
                ckpt_files = []
                for pattern in ckpt_patterns:
                    ckpt_files.extend(glob.glob(pattern, recursive=True))
                
                logger.info(f"🔍 Found checkpoint files: {[os.path.basename(f) for f in ckpt_files]}")
                
                if os.path.exists(cfg_path) and ckpt_files:
                    device = os.getenv("OPENVOICE_DEVICE", "cuda" if os.getenv("CUDA_VISIBLE_DEVICES", "") else "cpu")
                    logger.info(f"🚀 Initializing OpenVoice with device: {device}")
                    
                    try:
                        # Try different initialization methods for OpenVoice V2
                        converter = None
                        
                        # Method 1: With config path
                        try:
                            converter = ToneColorConverter(config_path=cfg_path, device=device)
                            logger.info("✅ OpenVoice initialized with config path")
                        except Exception as e1:
                            logger.warning(f"Method 1 failed: {e1}")
                            
                            # Method 2: Without config path
                            try:
                                converter = ToneColorConverter(device=device)
                                logger.info("✅ OpenVoice initialized without config path")
                            except Exception as e2:
                                logger.warning(f"Method 2 failed: {e2}")
                                raise e2
                        
                        if converter:
                            # Load checkpoint
                            ckpt_file = ckpt_files[0]  # Use first available checkpoint
                            logger.info(f"📦 Loading checkpoint: {os.path.basename(ckpt_file)}")
                            
                            if hasattr(converter, "load_ckpt"):
                                converter.load_ckpt(ckpt_file)
                                logger.info("✅ Checkpoint loaded via load_ckpt")
                            elif hasattr(converter, "load"):
                                converter.load(ckpt_path=ckpt_file)
                                logger.info("✅ Checkpoint loaded via load")
                            else:
                                raise AttributeError("No load method found on converter")
                            
                            # Test the converter
                            if hasattr(converter, 'convert'):
                                _CONVERT_FN = lambda audio, sr, src_se: converter.convert(
                                    audio=np.asarray(audio, dtype=np.float32), 
                                    sample_rate=int(sr), 
                                    src_se=src_se
                                )
                            elif hasattr(converter, 'tone_color_convert'):
                                _CONVERT_FN = lambda audio, sr, src_se: converter.tone_color_convert(
                                    np.asarray(audio, dtype=np.float32), 
                                    int(sr), 
                                    src_se
                                )
                            else:
                                raise AttributeError("No convert method found on converter")
                            
                            _CONVERTER = converter
                            logger.info("✅ OpenVoice V2 converter loaded successfully")
                        else:
                            raise Exception("Failed to initialize converter")
                            
                    except Exception as init_error:
                        logger.error(f"❌ OpenVoice initialization failed: {init_error}")
                        _CONVERTER = None
                        _CONVERT_FN = None
                        
                else:
                    missing = []
                    if not os.path.exists(cfg_path):
                        missing.append("config.json")
                    if not ckpt_files:
                        missing.append("checkpoint files")
                    logger.warning(f"⚠️ OpenVoice files missing: {missing} - voice cloning disabled")
            else:
                logger.warning(f"⚠️ OpenVoice directory not found: {conv_root} - voice cloning disabled")
                
        except ImportError as e:
            logger.warning(f"⚠️ OpenVoice not available: {e}")
            _CONVERTER = None
        except Exception as e:
            logger.warning(f"⚠️ Could not load OpenVoice converter: {e}")
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
        
        # Log GPU status
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"🚀 GPU detected: {gpu_name}")
            else:
                logger.warning("⚠️ No GPU detected, using CPU")
        except ImportError:
            logger.warning("⚠️ PyTorch not available for GPU detection")
            
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
    """Synthesize speech to WAV file path with OpenVoice V2 support"""
    
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
    
    melo_lang = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JA", "ko": "KO"}.get(lang, "EN")
    
    # Try to convert speaker ID to int
    try:
        spk = int(os.getenv("MELO_SPEAKER_ID", "0"))
    except ValueError:
        spk = 0
    
    # Check if we should use voice cloning
    use_voice_cloning = _CONVERTER is not None and _CONVERT_FN is not None and (reference_b64 or reference_url)
    
    if use_voice_cloning:
        logger.info("🎭 Using OpenVoice V2 voice cloning")
        
        # Prepare reference audio
        ref_path = None
        if reference_b64:
            ref_path = await _write_reference_b64(reference_b64)
        elif reference_url:
            ref_path = await _download_reference(reference_url)
        
        if not ref_path:
            logger.warning("⚠️ No reference audio provided, falling back to basic TTS")
            use_voice_cloning = False
    
    # Generate base TTS audio
    logger.info(f"🔊 Generating TTS with MeloTTS (language: {melo_lang}, speaker: {spk})")
    
    if hasattr(_MELO, "tts_to_file"):
        fd, base_path = tempfile.mkstemp(prefix="melo-base-", suffix=".wav")
        os.close(fd)
        
        try:
            _MELO.tts_to_file(
                text=text,
                speaker_id=spk,
                speed=speed,
                language=melo_lang,
                output_path=base_path
            )
        except TypeError:
            # Try without language parameter for older versions
            _MELO.tts_to_file(
                text=text,
                speaker_id=spk,
                speed=speed,
                output_path=base_path
            )
            
        if use_voice_cloning:
            # Apply voice cloning
            try:
                logger.info("🎭 Applying voice cloning transformation...")
                
                # Read base audio
                base_audio, sr = sf.read(base_path, dtype="float32")
                
                # Extract speaker embedding from reference
                from openvoice import se_extractor
                try:
                    src_se, _ = se_extractor.get_se(ref_path, _CONVERTER, vad=True)
                except TypeError:
                    src_se = se_extractor.get_se(ref_path)
                
                # Apply voice conversion
                converted_audio = _CONVERT_FN(base_audio, sr, src_se)
                
                # Save converted audio
                fd, out_path = tempfile.mkstemp(prefix="june-tts-v2-", suffix=".wav")
                os.close(fd)
                sf.write(out_path, converted_audio, sr, subtype="PCM_16")
                
                # Cleanup
                os.unlink(base_path)
                if ref_path:
                    asyncio.create_task(_cleanup_file(ref_path))
                
                logger.info("✅ Voice cloning applied successfully")
                return out_path
                
            except Exception as e:
                logger.error(f"❌ Voice cloning failed: {e}, falling back to base TTS")
                # Clean up and fall through to return base audio
                if ref_path:
                    asyncio.create_task(_cleanup_file(ref_path))
        
        return base_path
    
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
        
        # Apply voice cloning if available
        if use_voice_cloning:
            try:
                # Extract speaker embedding from reference
                from openvoice import se_extractor
                try:
                    src_se, _ = se_extractor.get_se(ref_path, _CONVERTER, vad=True)
                except TypeError:
                    src_se = se_extractor.get_se(ref_path)
                
                # Apply voice conversion
                converted_audio = _CONVERT_FN(audio, sr, src_se)
                audio = converted_audio
                
                # Cleanup
                if ref_path:
                    asyncio.create_task(_cleanup_file(ref_path))
                    
                logger.info("✅ Voice cloning applied successfully")
                
            except Exception as e:
                logger.error(f"❌ Voice cloning failed: {e}, using base TTS")
                if ref_path:
                    asyncio.create_task(_cleanup_file(ref_path))
        
        fd, out_path = tempfile.mkstemp(prefix="june-tts-", suffix=".wav")
        os.close(fd)
        sf.write(out_path, np.asarray(audio, dtype=np.float32), sr, subtype="PCM_16")
        return out_path
    
    else:
        raise RuntimeError("Unsupported MeloTTS build - no tts_to_file or tts_to_audio method")

async def _write_reference_b64(b64: str) -> str:
    """Write base64 reference audio to temporary file"""
    raw = base64.b64decode(b64)
    if len(raw) > _MAX_REF_BYTES:
        raise ValueError("reference_b64 too large")
    fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".wav")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(raw)
    return path

async def _download_reference(url: str) -> str:
    """Download reference audio from URL"""
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        if len(r.content) > _MAX_REF_BYTES:
            raise ValueError("reference_url file too large")
        fd, path = tempfile.mkstemp(prefix="ov2-ref-", suffix=".wav")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(r.content)
        return path

async def _cleanup_file(path: str):
    """Cleanup temporary file"""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

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
            if _CONVERTER:
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