# app/core/openvoice_engine.py - OPTIMIZED for Memory and Latency
import asyncio
import base64
import glob
import os
import tempfile
import time
import hashlib
from typing import Optional, Tuple, Dict, Any, List
import logging
from functools import lru_cache
import threading
import psutil

import httpx
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

# Configuration from official docs
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}
_CACHE_SIZE = int(os.getenv("TTS_CACHE_SIZE", "100"))
_ENABLE_QUANTIZATION = os.getenv("ENABLE_QUANTIZATION", "true").lower() == "true"

# Performance optimizations
torch.set_float32_matmul_precision('medium')
if torch.cuda.is_available():
    torch.backends.cudnn.benchmark = True
    # Optimize CUDA memory allocation
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512'

# Language mapping for MeloTTS (official mapping)
_MELO_LANGUAGE_MAP = {
    "en": "EN",
    "es": "ES", 
    "fr": "FR",
    "zh": "ZH",
    "ja": "JP",
    "ko": "KR"
}

# Global state with lazy loading
_MELO = None
_CONVERTER = None
_INITIALIZED = False
_MODEL_LOCK = threading.Lock()
_AVAILABLE_FEATURES = {
    "basic_tts": False,
    "voice_cloning": False,
    "multi_language": False
}

# Cache for TTS results
_tts_cache = {}
_embedding_cache = {}

def log_memory_usage(context: str = ""):
    """Log current memory usage"""
    try:
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.memory_allocated() / 1024**3
            gpu_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"[{context}] GPU Memory: {gpu_memory:.2f}GB / {gpu_total:.1f}GB")
        
        process = psutil.Process()
        ram_usage = process.memory_info().rss / 1024**3
        logger.info(f"[{context}] RAM Usage: {ram_usage:.2f}GB")
    except Exception as e:
        logger.warning(f"Could not log memory usage: {e}")

def _ensure_checkpoints() -> Tuple[str, str, str]:
    """Validate OpenVoice V2 checkpoint structure"""
    root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "converter")
    
    if not os.path.isdir(conv_root):
        conv_root = os.path.join(root, "tone_color_converter")
    
    logger.info(f"Checking OpenVoice V2 checkpoints: {conv_root}")
    return root, base_root, conv_root

def _find_converter_files(conv_root: str) -> Tuple[Optional[str], Optional[str]]:
    """Find config and checkpoint files using official V2 structure"""
    config_file = None
    checkpoint_file = None
    
    config_paths = [
        os.path.join(conv_root, "config.json"),
        os.path.join(conv_root, "model_config.json"),
    ]
    
    for path in config_paths:
        if os.path.exists(path):
            config_file = path
            break
    
    checkpoint_patterns = [
        os.path.join(conv_root, "*.pth"),
        os.path.join(conv_root, "**/*.pth"),
        os.path.join(conv_root, "*.pt"),
        os.path.join(conv_root, "**/*.pt"),
    ]
    
    for pattern in checkpoint_patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            checkpoint_file = matches[0]
            break
    
    logger.info(f"Found config: {config_file}, checkpoint: {checkpoint_file}")
    return config_file, checkpoint_file

def _load_melo_lazy() -> Any:
    """Lazy load MeloTTS model"""
    global _MELO
    
    if _MELO is not None:
        return _MELO
    
    with _MODEL_LOCK:
        if _MELO is not None:  # Double-check locking
            return _MELO
        
        logger.info("🚀 Lazy loading MeloTTS...")
        log_memory_usage("Before MeloTTS")
        
        try:
            from melo.api import TTS as MeloTTS
            
            device = os.getenv("OPENVOICE_DEVICE", "auto")
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            
            # Load with memory optimization
            with torch.inference_mode():
                _MELO = MeloTTS(language="EN", device=device)
                
                # Apply quantization if enabled
                if _ENABLE_QUANTIZATION and hasattr(_MELO, 'model'):
                    try:
                        _MELO.model = torch.quantization.quantize_dynamic(
                            _MELO.model, {torch.nn.Linear}, dtype=torch.qint8
                        )
                        logger.info("✅ Applied dynamic quantization to MeloTTS")
                    except Exception as e:
                        logger.warning(f"Quantization failed: {e}")
            
            _AVAILABLE_FEATURES["basic_tts"] = True
            _AVAILABLE_FEATURES["multi_language"] = True
            
            log_memory_usage("After MeloTTS")
            logger.info(f"✅ MeloTTS loaded on device: {device}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load MeloTTS: {e}")
            raise RuntimeError(f"MeloTTS loading failed: {e}")
        
        return _MELO

def _load_converter_lazy() -> Any:
    """Lazy load OpenVoice converter"""
    global _CONVERTER
    
    if _CONVERTER is not None:
        return _CONVERTER
    
    with _MODEL_LOCK:
        if _CONVERTER is not None:  # Double-check locking
            return _CONVERTER
        
        logger.info("🚀 Lazy loading OpenVoice Converter...")
        log_memory_usage("Before Converter")
        
        try:
            from openvoice.api import ToneColorConverter
            
            root, base_root, conv_root = _ensure_checkpoints()
            
            if not os.path.isdir(conv_root):
                logger.warning(f"⚠️ Converter directory not found: {conv_root}")
                _AVAILABLE_FEATURES["voice_cloning"] = False
                return None
            
            config_file, checkpoint_file = _find_converter_files(conv_root)
            
            if not config_file or not checkpoint_file:
                logger.warning(f"⚠️ Missing files - config: {config_file}, checkpoint: {checkpoint_file}")
                _AVAILABLE_FEATURES["voice_cloning"] = False
                return None
            
            device = os.getenv("OPENVOICE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
            
            with torch.inference_mode():
                _CONVERTER = ToneColorConverter(config_file, device=device)
                _CONVERTER.load_ckpt(checkpoint_file)
                
                # Apply quantization if enabled
                if _ENABLE_QUANTIZATION and hasattr(_CONVERTER, 'model'):
                    try:
                        _CONVERTER.model = torch.quantization.quantize_dynamic(
                            _CONVERTER.model, {torch.nn.Linear}, dtype=torch.qint8
                        )
                        logger.info("✅ Applied dynamic quantization to Converter")
                    except Exception as e:
                        logger.warning(f"Converter quantization failed: {e}")
            
            _AVAILABLE_FEATURES["voice_cloning"] = True
            log_memory_usage("After Converter")
            logger.info("✅ OpenVoice V2 converter loaded")
            
        except ImportError as ie:
            logger.warning(f"⚠️ OpenVoice not available: {ie}")
            _AVAILABLE_FEATURES["voice_cloning"] = False
            return None
        except Exception as e:
            logger.error(f"❌ Converter loading failed: {e}")
            _AVAILABLE_FEATURES["voice_cloning"] = False
            return None
        
        return _CONVERTER

def _get_cache_key(text: str, language: str, speed: float, reference_data: str = "") -> str:
    """Generate cache key for TTS request"""
    combined = f"{text}:{language}:{speed}:{reference_data}"
    return hashlib.md5(combined.encode()).hexdigest()

@lru_cache(maxsize=_CACHE_SIZE)
def _cached_speaker_embedding(ref_path_hash: str, ref_path: str) -> Any:
    """Cache speaker embeddings"""
    try:
        from openvoice import se_extractor
        converter = _load_converter_lazy()
        if converter is None:
            return None
        
        logger.info(f"🎯 Extracting speaker embedding (cached)")
        target_se, _ = se_extractor.get_se(ref_path, converter, vad=True)
        return target_se
    except Exception as e:
        logger.error(f"❌ Embedding extraction failed: {e}")
        return None

def warmup_models() -> None:
    """Optimized warmup - only test basic functionality"""
    global _INITIALIZED
    
    if _INITIALIZED:
        return
    
    try:
        logger.info("🧪 Performing optimized warmup...")
        log_memory_usage("Before Warmup")
        
        # Test basic TTS with minimal text
        melo = _load_melo_lazy()
        if melo:
            logger.info("🧪 Testing basic TTS with minimal load...")
            try:
                test_text = "Hi"
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp_file:
                    with torch.inference_mode():
                        melo.tts_to_file(test_text, 0, tmp_file.name, speed=1.0)
                    if os.path.exists(tmp_file.name) and os.path.getsize(tmp_file.name) > 100:
                        logger.info("✅ Basic TTS warmup passed")
                    else:
                        logger.warning("⚠️ Basic TTS warmup produced small file")
            except Exception as e:
                logger.warning(f"⚠️ Basic TTS warmup failed: {e}")
        
        # Note: Don't load converter during warmup - load on demand
        logger.info("ℹ️ Converter will load on first voice cloning request")
        
        _INITIALIZED = True
        log_memory_usage("After Warmup")
        logger.info("🎉 Optimized warmup complete!")
        
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
    """Optimized synthesis with caching and streaming support"""
    
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
    
    # Check cache first
    ref_data = reference_b64 or reference_url or ""
    cache_key = _get_cache_key(text, lang, speed, ref_data)
    
    if cache_key in _tts_cache:
        logger.info("🚀 Returning cached TTS result")
        # Copy cached file to new temporary file
        cached_path = _tts_cache[cache_key]
        if os.path.exists(cached_path):
            fd, new_path = tempfile.mkstemp(prefix="june-cached-", suffix=".wav")
            os.close(fd)
            import shutil
            shutil.copy2(cached_path, new_path)
            return new_path
        else:
            # Remove invalid cache entry
            del _tts_cache[cache_key]
    
    # Load models on demand
    melo = _load_melo_lazy()
    if not melo:
        raise RuntimeError("TTS service not available")
    
    melo_lang = _MELO_LANGUAGE_MAP.get(lang, "EN")
    
    # Determine if we should use voice cloning
    use_voice_cloning = (reference_b64 or reference_url)
    
    if use_voice_cloning:
        logger.info("🎭 Using OpenVoice V2 voice cloning")
        result_path = await _synthesize_with_cloning_optimized(
            text, melo_lang, reference_b64, reference_url, speed, volume, pitch
        )
    else:
        logger.info("🔊 Using optimized basic MeloTTS")
        result_path = await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
    
    # Cache result if successful and cache is not full
    if len(_tts_cache) < _CACHE_SIZE:
        # Create a permanent cache file
        cache_dir = os.path.join(tempfile.gettempdir(), "june_tts_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"tts_{cache_key}.wav")
        
        try:
            import shutil
            shutil.copy2(result_path, cache_path)
            _tts_cache[cache_key] = cache_path
            logger.info(f"💾 Cached TTS result: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to cache result: {e}")
    
    return result_path

async def _synthesize_basic_tts_optimized(
    text: str, 
    melo_lang: str, 
    speed: float, 
    volume: float, 
    pitch: float
) -> str:
    """Optimized basic TTS generation"""
    
    try:
        melo = _load_melo_lazy()
        
        # Get speaker ID
        speaker_ids = melo.hps.data.spk2id
        speaker_id = list(speaker_ids.values())[0] if speaker_ids else 0
        
        # Create output file
        fd, output_path = tempfile.mkstemp(prefix="june-basic-tts-", suffix=".wav")
        os.close(fd)
        
        # Generate with inference mode for optimization
        with torch.inference_mode():
            melo.tts_to_file(
                text=text,
                speaker_id=speaker_id,
                output_path=output_path,
                speed=speed
            )
        
        # Verify file
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise RuntimeError("TTS generation failed - empty or missing file")
        
        logger.info(f"✅ Basic TTS generated: {os.path.getsize(output_path)} bytes")
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Basic TTS failed: {e}")
        raise RuntimeError(f"TTS synthesis failed: {e}")

async def _synthesize_with_cloning_optimized(
    text: str,
    melo_lang: str, 
    reference_b64: Optional[str],
    reference_url: Optional[str],
    speed: float,
    volume: float,
    pitch: float
) -> str:
    """Optimized voice cloning synthesis"""
    
    # Load converter on demand
    converter = _load_converter_lazy()
    if not converter:
        logger.warning("⚠️ Converter not available, falling back to basic TTS")
        return await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
    
    ref_path = None
    try:
        # Get reference audio
        if reference_b64:
            ref_path = await _write_reference_b64(reference_b64)
        elif reference_url:
            ref_path = await _download_reference(reference_url)
        else:
            raise ValueError("No reference audio provided")
        
        # Generate base TTS
        base_path = await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
        
        # Extract speaker embedding with caching
        ref_hash = hashlib.md5(open(ref_path, 'rb').read()).hexdigest()
        target_se = _cached_speaker_embedding(ref_hash, ref_path)
        
        if target_se is None:
            logger.warning("⚠️ Failed to extract embedding, falling back to basic TTS")
            if ref_path:
                asyncio.create_task(_cleanup_file(ref_path))
            return base_path
        
        # Apply voice conversion
        logger.info("🎭 Applying optimized voice conversion...")
        converted_path = await _apply_voice_conversion_optimized(base_path, target_se)
        
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
        # Cleanup and fallback
        try:
            if ref_path:
                asyncio.create_task(_cleanup_file(ref_path))
        except Exception:
            pass
        
        logger.info("⚠️ Falling back to basic TTS")
        return await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)

async def _apply_voice_conversion_optimized(base_audio_path: str, target_se) -> str:
    """Optimized voice conversion"""
    
    try:
        converter = _load_converter_lazy()
        if not converter:
            raise RuntimeError("Converter not available")
        
        # Create output path
        fd, output_path = tempfile.mkstemp(prefix="june-cloned-", suffix=".wav")
        os.close(fd)
        
        # Load and convert with optimization
        audio, sr = sf.read(base_audio_path, dtype="float32")
        
        with torch.inference_mode():
            converted_audio = converter.convert(
                audio=np.asarray(audio, dtype=np.float32),
                sample_rate=int(sr),
                src_se=target_se
            )
        
        # Save result
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
        },
        "cache": {
            "tts_cache_size": len(_tts_cache),
            "tts_cache_max": _CACHE_SIZE
        },
        "optimization": {
            "quantization_enabled": _ENABLE_QUANTIZATION,
            "lazy_loading": True
        }
    }

def get_available_voices() -> Dict[str, Any]:
    """Get available voices and speakers"""
    if _MELO is None:
        # Don't load model just to get voices - return default info
        return {
            "speakers": {},
            "languages": list(_MELO_LANGUAGE_MAP.keys()),
            "voice_cloning_available": _AVAILABLE_FEATURES["voice_cloning"],
            "note": "Speakers will be available after first TTS request"
        }
    
    try:
        speaker_ids = _MELO.hps.data.spk2id
        return {
            "speakers": dict(speaker_ids) if speaker_ids else {},
            "languages": list(_MELO_LANGUAGE_MAP.keys()),
            "voice_cloning_available": _AVAILABLE_FEATURES["voice_cloning"]
        }
    except Exception as e:
        return {"error": str(e)}

def clear_cache():
    """Clear TTS cache"""
    global _tts_cache
    
    # Clean up cache files
    for cache_path in _tts_cache.values():
        try:
            if os.path.exists(cache_path):
                os.unlink(cache_path)
        except Exception:
            pass
    
    _tts_cache.clear()
    logger.info("🧹 TTS cache cleared")

# Engine class for compatibility
class OpenVoiceEngine:
    """Optimized engine class"""
    
    def __init__(self):
        self.converter = None
        self.initialized = False
        
    def initialize(self):
        """Initialize the engine"""
        try:
            # Don't actually load models here - use lazy loading
            self.initialized = True
            logger.info("✅ OpenVoice engine initialized with lazy loading")
                
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

# Initialize on import (lazy loading will happen on first use)
try:
    engine.initialize()
except Exception as e:
    logger.warning(f"⚠️ Engine initialization failed on import: {e}")
