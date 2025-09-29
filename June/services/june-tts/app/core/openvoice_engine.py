# app/core/openvoice_engine.py - ULTRA-OPTIMIZED for Latency
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
from concurrent.futures import ThreadPoolExecutor
import queue

import httpx
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

# Configuration
_MAX_REF_BYTES = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))
_MAX_TEXT_LEN = int(os.getenv("MAX_TEXT_LEN", "2000"))
_SUPPORTED_LANGUAGES = {"en", "es", "fr", "zh", "ja", "ko"}
_CACHE_SIZE = int(os.getenv("TTS_CACHE_SIZE", "500"))  # Increased from 100
_ENABLE_QUANTIZATION = os.getenv("ENABLE_QUANTIZATION", "true").lower() == "true"
_PRELOAD_MODELS = os.getenv("PRELOAD_MODELS", "true").lower() == "true"
_ENABLE_STREAMING = os.getenv("ENABLE_STREAMING", "true").lower() == "true"

# Performance optimizations
torch.set_float32_matmul_precision('medium')
torch.set_num_threads(4)
if torch.cuda.is_available():
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512,expandable_segments:True'

# Language mapping
_MELO_LANGUAGE_MAP = {
    "en": "EN", "es": "ES", "fr": "FR",
    "zh": "ZH", "ja": "JP", "ko": "KR"
}

# Global state
_MELO = None
_CONVERTER = None
_INITIALIZED = False
_MODEL_LOCK = threading.Lock()
_WARMUP_COMPLETE = threading.Event()
_AVAILABLE_FEATURES = {
    "basic_tts": False,
    "voice_cloning": False,
    "multi_language": False,
    "streaming": False
}

# Caches
_tts_cache = {}
_embedding_cache = {}
_audio_preprocessing_pool = ThreadPoolExecutor(max_workers=2)

# Pipeline optimization - Pre-allocated buffers
_pipeline_queue = queue.Queue(maxsize=10)
_result_cache_lock = threading.Lock()

def log_memory_usage(context: str = ""):
    """Log current memory usage"""
    try:
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.memory_allocated() / 1024**3
            gpu_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"[{context}] GPU: {gpu_memory:.2f}GB/{gpu_total:.1f}GB")
        
        process = psutil.Process()
        ram_usage = process.memory_info().rss / 1024**3
        logger.info(f"[{context}] RAM: {ram_usage:.2f}GB")
    except Exception as e:
        logger.warning(f"Memory logging failed: {e}")

def _ensure_checkpoints() -> Tuple[str, str, str]:
    """Validate checkpoint structure"""
    root = os.getenv("OPENVOICE_CHECKPOINTS_V2", "/models/openvoice/checkpoints_v2")
    base_root = os.path.join(root, "base_speakers")
    conv_root = os.path.join(root, "converter")
    
    if not os.path.isdir(conv_root):
        conv_root = os.path.join(root, "tone_color_converter")
    
    return root, base_root, conv_root

def _find_converter_files(conv_root: str) -> Tuple[Optional[str], Optional[str]]:
    """Find config and checkpoint files"""
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
    ]
    
    for pattern in checkpoint_patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            checkpoint_file = matches[0]
            break
    
    return config_file, checkpoint_file

def _load_melo_immediate() -> Any:
    """Load MeloTTS immediately with optimizations"""
    global _MELO
    
    if _MELO is not None:
        return _MELO
    
    with _MODEL_LOCK:
        if _MELO is not None:
            return _MELO
        
        logger.info("🚀 Loading MeloTTS (optimized)...")
        start_time = time.time()
        
        try:
            from melo.api import TTS as MeloTTS
            
            device = os.getenv("OPENVOICE_DEVICE", "auto")
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            
            with torch.inference_mode():
                _MELO = MeloTTS(language="EN", device=device)
                
                # Apply optimizations
                if hasattr(_MELO, 'model'):
                    _MELO.model.eval()
                    
                    if _ENABLE_QUANTIZATION and device == "cuda":
                        try:
                            _MELO.model = torch.quantization.quantize_dynamic(
                                _MELO.model, {torch.nn.Linear}, dtype=torch.qint8
                            )
                            logger.info("✅ Quantized MeloTTS")
                        except Exception as e:
                            logger.warning(f"Quantization failed: {e}")
                    
                    # Compile model for faster inference (PyTorch 2.0+)
                    if hasattr(torch, 'compile') and device == "cuda":
                        try:
                            _MELO.model = torch.compile(_MELO.model, mode="reduce-overhead")
                            logger.info("✅ Compiled MeloTTS with torch.compile")
                        except Exception as e:
                            logger.warning(f"Compilation failed: {e}")
            
            _AVAILABLE_FEATURES["basic_tts"] = True
            _AVAILABLE_FEATURES["multi_language"] = True
            
            load_time = time.time() - start_time
            logger.info(f"✅ MeloTTS loaded in {load_time:.2f}s on {device}")
            
        except Exception as e:
            logger.error(f"❌ MeloTTS loading failed: {e}")
            raise RuntimeError(f"MeloTTS loading failed: {e}")
        
        return _MELO

def _load_converter_immediate() -> Any:
    """Load converter immediately with optimizations"""
    global _CONVERTER
    
    if _CONVERTER is not None:
        return _CONVERTER
    
    with _MODEL_LOCK:
        if _CONVERTER is not None:
            return _CONVERTER
        
        logger.info("🚀 Loading OpenVoice Converter (optimized)...")
        start_time = time.time()
        
        try:
            from openvoice.api import ToneColorConverter
            
            root, base_root, conv_root = _ensure_checkpoints()
            
            if not os.path.isdir(conv_root):
                logger.warning(f"⚠️ Converter directory not found: {conv_root}")
                _AVAILABLE_FEATURES["voice_cloning"] = False
                return None
            
            config_file, checkpoint_file = _find_converter_files(conv_root)
            
            if not config_file or not checkpoint_file:
                logger.warning(f"⚠️ Missing converter files")
                _AVAILABLE_FEATURES["voice_cloning"] = False
                return None
            
            device = os.getenv("OPENVOICE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
            
            with torch.inference_mode():
                _CONVERTER = ToneColorConverter(config_file, device=device)
                _CONVERTER.load_ckpt(checkpoint_file)
                
                # Optimize converter
                if hasattr(_CONVERTER, 'model'):
                    _CONVERTER.model.eval()
                    
                    if _ENABLE_QUANTIZATION and device == "cuda":
                        try:
                            _CONVERTER.model = torch.quantization.quantize_dynamic(
                                _CONVERTER.model, {torch.nn.Linear}, dtype=torch.qint8
                            )
                            logger.info("✅ Quantized Converter")
                        except Exception as e:
                            logger.warning(f"Converter quantization failed: {e}")
                    
                    # Compile converter model
                    if hasattr(torch, 'compile') and device == "cuda":
                        try:
                            _CONVERTER.model = torch.compile(_CONVERTER.model, mode="reduce-overhead")
                            logger.info("✅ Compiled Converter with torch.compile")
                        except Exception as e:
                            logger.warning(f"Converter compilation failed: {e}")
            
            _AVAILABLE_FEATURES["voice_cloning"] = True
            _AVAILABLE_FEATURES["streaming"] = _ENABLE_STREAMING
            
            load_time = time.time() - start_time
            logger.info(f"✅ Converter loaded in {load_time:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ Converter loading failed: {e}")
            _AVAILABLE_FEATURES["voice_cloning"] = False
            return None
        
        return _CONVERTER

def _get_cache_key(text: str, language: str, speed: float, reference_data: str = "") -> str:
    """Generate cache key"""
    combined = f"{text}:{language}:{speed}:{reference_data}"
    return hashlib.md5(combined.encode()).hexdigest()

@lru_cache(maxsize=_CACHE_SIZE)
def _cached_speaker_embedding(ref_path_hash: str, ref_path: str) -> Any:
    """Cache speaker embeddings with larger cache"""
    try:
        from openvoice import se_extractor
        converter = _CONVERTER
        if converter is None:
            return None
        
        logger.debug(f"🎯 Extracting speaker embedding")
        with torch.inference_mode():
            target_se, _ = se_extractor.get_se(ref_path, converter, vad=True)
        return target_se
    except Exception as e:
        logger.error(f"❌ Embedding extraction failed: {e}")
        return None

def warmup_models_aggressive() -> None:
    """Aggressive warmup - preload everything"""
    global _INITIALIZED
    
    if _INITIALIZED:
        _WARMUP_COMPLETE.set()
        return
    
    try:
        logger.info("🔥 AGGRESSIVE WARMUP: Preloading all models...")
        log_memory_usage("Before Aggressive Warmup")
        
        start_time = time.time()
        
        # Load MeloTTS immediately
        melo = _load_melo_immediate()
        
        # Load Converter immediately if requested
        if _PRELOAD_MODELS:
            converter = _load_converter_immediate()
        
        # Perform actual synthesis warmup
        logger.info("🧪 Running synthesis warmup...")
        test_texts = ["Hello", "Testing", "Quick warmup"]
        
        for text in test_texts:
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp_file:
                    with torch.inference_mode():
                        if hasattr(melo, 'tts_to_file'):
                            melo.tts_to_file(text, 0, tmp_file.name, speed=1.0)
                        logger.debug(f"✅ Warmup synthesis: {text}")
            except Exception as e:
                logger.warning(f"⚠️ Warmup synthesis failed for '{text}': {e}")
        
        # Clear CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        _INITIALIZED = True
        _WARMUP_COMPLETE.set()
        
        warmup_time = time.time() - start_time
        log_memory_usage("After Aggressive Warmup")
        logger.info(f"🎉 AGGRESSIVE WARMUP COMPLETE in {warmup_time:.2f}s!")
        logger.info(f"📊 Features ready: {_AVAILABLE_FEATURES}")
        
    except Exception as e:
        logger.error(f"❌ Aggressive warmup failed: {e}")
        _INITIALIZED = False

def wait_for_warmup(timeout: float = 60.0) -> bool:
    """Wait for warmup to complete"""
    return _WARMUP_COMPLETE.wait(timeout=timeout)

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
    """Ultra-optimized synthesis with all features"""
    
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
    
    # Wait for warmup if not ready
    if not _INITIALIZED:
        logger.info("⏳ Waiting for model warmup...")
        if not wait_for_warmup(timeout=30.0):
            logger.warning("⚠️ Warmup timeout, proceeding anyway")
    
    # Check cache
    ref_data = reference_b64 or reference_url or ""
    cache_key = _get_cache_key(text, lang, speed, ref_data)
    
    with _result_cache_lock:
        if cache_key in _tts_cache:
            logger.info("🚀 Cache HIT")
            cached_path = _tts_cache[cache_key]
            if os.path.exists(cached_path):
                fd, new_path = tempfile.mkstemp(prefix="june-cached-", suffix=".wav")
                os.close(fd)
                import shutil
                shutil.copy2(cached_path, new_path)
                return new_path
            else:
                del _tts_cache[cache_key]
    
    # Get models (should be instant after warmup)
    melo = _MELO if _INITIALIZED else _load_melo_immediate()
    if not melo:
        raise RuntimeError("TTS service not available")
    
    melo_lang = _MELO_LANGUAGE_MAP.get(lang, "EN")
    use_voice_cloning = bool(reference_b64 or reference_url)
    
    if use_voice_cloning:
        logger.info("🎭 Voice cloning synthesis")
        result_path = await _synthesize_with_cloning_optimized(
            text, melo_lang, reference_b64, reference_url, speed, volume, pitch
        )
    else:
        logger.info("🔊 Basic TTS synthesis")
        result_path = await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
    
    # Cache result
    if len(_tts_cache) < _CACHE_SIZE:
        cache_dir = os.path.join(tempfile.gettempdir(), "june_tts_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"tts_{cache_key}.wav")
        
        try:
            import shutil
            shutil.copy2(result_path, cache_path)
            with _result_cache_lock:
                _tts_cache[cache_key] = cache_path
            logger.debug(f"💾 Cached: {cache_key}")
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
    
    return result_path

async def _synthesize_basic_tts_optimized(
    text: str, 
    melo_lang: str, 
    speed: float, 
    volume: float, 
    pitch: float
) -> str:
    """Optimized basic TTS with minimal overhead"""
    
    try:
        melo = _MELO
        speaker_ids = melo.hps.data.spk2id
        speaker_id = list(speaker_ids.values())[0] if speaker_ids else 0
        
        fd, output_path = tempfile.mkstemp(prefix="june-tts-", suffix=".wav")
        os.close(fd)
        
        # Ultra-fast synthesis with all optimizations
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=torch.cuda.is_available()):
            melo.tts_to_file(
                text=text,
                speaker_id=speaker_id,
                output_path=output_path,
                speed=speed
            )
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise RuntimeError("TTS generation failed")
        
        logger.debug(f"✅ TTS: {os.path.getsize(output_path)} bytes")
        return output_path
        
    except Exception as e:
        logger.error(f"❌ TTS failed: {e}")
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
    """Optimized voice cloning with parallel processing"""
    
    converter = _CONVERTER
    if not converter:
        logger.warning("⚠️ Converter unavailable, using basic TTS")
        return await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
    
    ref_path = None
    try:
        # Get reference audio
        if reference_b64:
            ref_path = await _write_reference_b64(reference_b64)
        elif reference_url:
            ref_path = await _download_reference(reference_url)
        else:
            raise ValueError("No reference audio")
        
        # Parallel execution: Start base TTS while extracting embedding
        base_tts_task = asyncio.create_task(
            _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)
        )
        
        # Extract embedding in parallel
        ref_hash = hashlib.md5(open(ref_path, 'rb').read()).hexdigest()
        target_se = _cached_speaker_embedding(ref_hash, ref_path)
        
        if target_se is None:
            logger.warning("⚠️ Embedding failed, using basic TTS")
            base_path = await base_tts_task
            if ref_path:
                asyncio.create_task(_cleanup_file(ref_path))
            return base_path
        
        # Wait for base TTS
        base_path = await base_tts_task
        
        # Apply conversion with all optimizations
        logger.info("🎭 Applying voice conversion")
        converted_path = await _apply_voice_conversion_optimized(base_path, target_se)
        
        # Cleanup
        try:
            os.unlink(base_path)
            if ref_path:
                asyncio.create_task(_cleanup_file(ref_path))
        except Exception:
            pass
        
        logger.info("✅ Voice cloning complete")
        return converted_path
        
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        if ref_path:
            asyncio.create_task(_cleanup_file(ref_path))
        
        logger.info("⚠️ Fallback to basic TTS")
        return await _synthesize_basic_tts_optimized(text, melo_lang, speed, volume, pitch)

async def _apply_voice_conversion_optimized(base_audio_path: str, target_se) -> str:
    """Optimized voice conversion with CUDA acceleration"""
    
    try:
        converter = _CONVERTER
        if not converter:
            raise RuntimeError("Converter unavailable")
        
        fd, output_path = tempfile.mkstemp(prefix="june-cloned-", suffix=".wav")
        os.close(fd)
        
        # Load audio
        audio, sr = sf.read(base_audio_path, dtype="float32")
        
        # Ultra-fast conversion with all optimizations
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=torch.cuda.is_available()):
            converted_audio = converter.convert(
                audio=np.asarray(audio, dtype=np.float32),
                sample_rate=int(sr),
                src_se=target_se
            )
        
        sf.write(output_path, converted_audio, sr, subtype="PCM_16")
        
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Conversion failed: {e}")
        raise

async def _write_reference_b64(b64: str) -> str:
    """Write base64 reference"""
    try:
        raw = base64.b64decode(b64)
        if len(raw) > _MAX_REF_BYTES:
            raise ValueError("Reference too large")
        
        fd, path = tempfile.mkstemp(prefix="ref-", suffix=".wav")
        os.close(fd)
        
        with open(path, "wb") as f:
            f.write(raw)
        
        return path
    except Exception as e:
        logger.error(f"❌ Reference processing failed: {e}")
        raise

async def _download_reference(url: str) -> str:
    """Download reference audio"""
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            if len(response.content) > _MAX_REF_BYTES:
                raise ValueError("Reference too large")
            
            fd, path = tempfile.mkstemp(prefix="ref-", suffix=".wav")
            os.close(fd)
            
            with open(path, "wb") as f:
                f.write(response.content)
            
            return path
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        raise

async def _cleanup_file(path: str):
    """Async cleanup"""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

def get_engine_status() -> Dict[str, Any]:
    """Get engine status"""
    return {
        "initialized": _INITIALIZED,
        "warmup_complete": _WARMUP_COMPLETE.is_set(),
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
            "tts_cache_max": _CACHE_SIZE,
            "embedding_cache_info": _cached_speaker_embedding.cache_info()._asdict()
        },
        "optimization": {
            "quantization_enabled": _ENABLE_QUANTIZATION,
            "preload_enabled": _PRELOAD_MODELS,
            "streaming_enabled": _ENABLE_STREAMING,
            "torch_compile": hasattr(torch, 'compile')
        }
    }

def clear_cache():
    """Clear all caches"""
    global _tts_cache
    
    for cache_path in _tts_cache.values():
        try:
            if os.path.exists(cache_path):
                os.unlink(cache_path)
        except Exception:
            pass
    
    _tts_cache.clear()
    _cached_speaker_embedding.cache_clear()
    
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    logger.info("🧹 All caches cleared")

# Compatibility class
class OpenVoiceEngine:
    def __init__(self):
        self.converter = None
        self.initialized = False
        
    def initialize(self):
        try:
            warmup_models_aggressive()
            self.initialized = True
            self.converter = _CONVERTER
            logger.info("✅ Engine initialized")
        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            self.converter = None
            self.initialized = False
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: str = "EN",
        speed: float = 1.0
    ) -> bytes:
        ref_b64 = base64.b64encode(reference_audio_bytes).decode('utf-8')
        
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
        
        with open(wav_path, 'rb') as f:
            audio_data = f.read()
        
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        
        return audio_data

# Global instance
engine = OpenVoiceEngine()

# Auto-initialize with aggressive warmup if PRELOAD_MODELS is enabled
if _PRELOAD_MODELS:
    logger.info("🔥 AUTO-INITIALIZATION: Starting aggressive warmup")
    import threading
    warmup_thread = threading.Thread(target=warmup_models_aggressive, daemon=True)
    warmup_thread.start()
else:
    logger.info("ℹ️ Lazy loading enabled - models will load on first request")