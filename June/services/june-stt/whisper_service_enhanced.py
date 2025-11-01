"""
Enhanced Whisper Service
Combines faster-whisper-server optimizations with existing June STT functionality
Includes dynamic model loading, better resource management, and OpenAI compatibility
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List

import torch
import numpy as np
from faster_whisper import WhisperModel, BatchedInferencePipeline

from config_enhanced import config

logger = logging.getLogger(__name__)

class EnhancedWhisperService:
    """
    Enhanced Whisper service combining:
    - faster-whisper-server dynamic model loading
    - Batch processing capabilities
    - Resource management
    - OpenAI API compatibility
    - LiveKit real-time processing optimization
    """
    
    def __init__(self):
        self.model = None
        self.batched_pipeline = None
        self.is_ready = threading.Event()
        self.load_error = None
        self.model_lock = asyncio.Lock()
        self.last_used = time.time()
        self._model_usage_count = 0
        
    async def initialize(self):
        """Initialize model with enhanced loading strategy"""
        if self.model and not self.load_error:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"🎯 Loading Enhanced Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            logger.info(f"📦 Features: Batched={config.USE_BATCHED_INFERENCE}, Dynamic={config.DYNAMIC_MODEL_LOADING}, VAD={config.VAD_ENABLED}")
            
            # Log configuration
            config.log_configuration()
            
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._create_model)
            
            # Initialize batched pipeline if enabled (recommended for throughput)
            if config.USE_BATCHED_INFERENCE:
                logger.info("⚡ Initializing Enhanced BatchedInferencePipeline...")
                self.batched_pipeline = BatchedInferencePipeline(model=self.model)
                logger.info("✅ Enhanced batched inference ready - includes optimized silence removal")
            
            self.is_ready.set()
            self.last_used = time.time()
            logger.info("🚀 Enhanced Whisper service ready for both file processing and real-time chat")
            
        except Exception as e:
            logger.error(f"❌ Enhanced model initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _create_model(self) -> WhisperModel:
        """Create model with enhanced configuration"""
        # Determine optimal compute type based on device
        compute_type = config.WHISPER_COMPUTE_TYPE
        if config.WHISPER_DEVICE == "cpu":
            compute_type = "int8"  # Better for CPU
        elif config.WHISPER_DEVICE == "cuda" and torch.cuda.is_available():
            # Use mixed precision if available
            compute_type = "float16" if torch.cuda.get_device_capability()[0] >= 7 else "float32"
            
        logger.info(f"🔧 Creating model with compute_type={compute_type}, device={config.WHISPER_DEVICE}")
        
        return WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=compute_type,
            cpu_threads=config.WHISPER_CPU_THREADS if config.WHISPER_DEVICE == "cpu" else 0,
            num_workers=config.WHISPER_NUM_WORKERS,
            download_root=config.WHISPER_CACHE_DIR,
            local_files_only=False
        )
    
    def is_model_ready(self) -> bool:
        """Check if model is ready for inference"""
        return self.is_ready.is_set() and self.model is not None and not self.load_error
    
    def _update_usage(self):
        """Update model usage statistics"""
        self.last_used = time.time()
        self._model_usage_count += 1
    
    def _should_unload_model(self) -> bool:
        """Check if model should be unloaded (dynamic loading feature)"""
        if not config.DYNAMIC_MODEL_LOADING:
            return False
            
        idle_time = time.time() - self.last_used
        return idle_time > config.MODEL_UNLOAD_TIMEOUT
    
    async def _maybe_unload_model(self):
        """Unload model if idle (dynamic loading feature)"""
        if self._should_unload_model() and self.model:
            async with self.model_lock:
                logger.info("📋 Unloading model due to inactivity (dynamic loading)")
                if self.batched_pipeline:
                    del self.batched_pipeline
                    self.batched_pipeline = None
                if self.model:
                    del self.model
                    self.model = None
                    
                # Clear GPU cache if using CUDA
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    
                self.is_ready.clear()
                logger.info("✅ Model unloaded, memory freed")
    
    def _optional_rms_check(self, audio_path: str) -> bool:
        """Optional RMS-based prefilter (from original implementation)"""
        if not config.RMS_PREFILTER_ENABLED:
            return True  # Skip prefilter
            
        try:
            import soundfile as sf
            audio, sr = sf.read(audio_path)
            
            if not isinstance(audio, np.ndarray):
                audio = np.array(audio)
            
            rms = np.sqrt(np.mean(audio ** 2))
            has_energy = rms > config.SILENCE_RMS_THRESHOLD
            
            if not has_energy:
                logger.debug(f"🔇 RMS prefilter: too quiet (RMS={rms:.6f})")
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"RMS prefilter failed: {e}, proceeding anyway")
            return True
    
    def _enhanced_noise_filter(self, text: str, segments: List) -> bool:
        """Enhanced noise filtering combining both approaches"""
        if not text or len(text.strip()) == 0:
            return False
        
        clean_text = text.lower().strip()
        
        # Filter single non-alphabetic characters
        if len(clean_text) == 1 and not clean_text.isalpha():
            logger.debug(f"🗑️ Filtered single non-alphabetic: '{text}'")
            return False
        
        # Enhanced filtering for common false positives
        false_positives = {
            "you", "you.", "uh", "um", "ah", "mm", "hm", "er", "eh", "oh",
            "thanks", "thank you", "okay", "ok", "yeah", "yes", "no", "hi", "hello"
        }
        
        if clean_text in false_positives and len(clean_text) <= 3:
            logger.debug(f"🗑️ Filtered false positive: '{text}'")
            return False
        
        # Segment-based filtering (if available)
        if segments and len(segments) > 0:
            try:
                avg_length = sum(len(seg.text.strip()) for seg in segments) / len(segments)
                if avg_length <= 2 and len(clean_text) <= 3:
                    logger.debug(f"🗽1️ Filtered very short low-content: '{text}'")
                    return False
            except:
                pass
        
        return True
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Enhanced transcription with both file processing and real-time optimization
        Supports OpenAI API compatibility and real-time voice chat requirements
        """
        if not self.is_model_ready():
            # Try to reinitialize if model was unloaded
            if config.DYNAMIC_MODEL_LOADING:
                await self.initialize()
            else:
                raise RuntimeError("Enhanced Whisper model not ready")
        
        # Update usage tracking
        self._update_usage()
        
        start_time = time.time()
        
        try:
            async with self.model_lock:
                # Optional RMS prefilter
                if not self._optional_rms_check(audio_path):
                    return {
                        "text": "",
                        "language": language or config.LANGUAGE or "en",
                        "language_probability": 0.0,
                        "processing_time_ms": int((time.time() - start_time) * 1000),
                        "segments": [],
                        "skipped_reason": "rms_prefilter",
                        "method": "enhanced"
                    }

                # Use configured or provided language for better performance
                target_language = language or config.LANGUAGE
                
                # Choose transcription method based on configuration
                if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                    segments, info = await self._transcribe_batched(audio_path, target_language)
                    method = "enhanced_batched"
                else:
                    segments, info = await self._transcribe_regular(audio_path, target_language)
                    method = "enhanced_regular"
                
                segment_list = list(segments)
                full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
                
                # Enhanced noise filtering
                if not self._enhanced_noise_filter(full_text, segment_list):
                    return {
                        "text": "",
                        "language": getattr(info, 'language', target_language or "en"),
                        "language_probability": getattr(info, 'language_probability', 0.0),
                        "processing_time_ms": int((time.time() - start_time) * 1000),
                        "segments": [],
                        "skipped_reason": "enhanced_noise_filter",
                        "method": method
                    }
                
                processing_time = int((time.time() - start_time) * 1000)
                
                # Enhanced segment logging
                if segment_list and logger.isEnabledFor(logging.DEBUG):
                    for i, seg in enumerate(segment_list[:3]):
                        confidence = getattr(seg, 'confidence', 'N/A')
                        logger.debug(f"  Enhanced Segment {i}: {seg.start:.2f}-{seg.end:.2f}s (conf: {confidence}): '{seg.text.strip()}'")
                
                logger.info(f"✅ Enhanced transcribed via {method} ({processing_time}ms): {full_text[:100]}{'...' if len(full_text) > 100 else ''}")
                
                # Schedule model unloading check if dynamic loading is enabled
                if config.DYNAMIC_MODEL_LOADING:
                    asyncio.create_task(self._maybe_unload_model())
                
                return {
                    "text": full_text,
                    "language": getattr(info, 'language', target_language or "en"),
                    "language_probability": getattr(info, 'language_probability', 0.0),
                    "processing_time_ms": processing_time,
                    "method": method,
                    "model_usage_count": self._model_usage_count,
                    "segments": [
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text.strip(),
                            "confidence": getattr(segment, 'confidence', None)
                        } for segment in segment_list
                    ]
                }
                
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"❌ Enhanced transcription failed after {processing_time}ms: {e}")
            raise
    
    async def _transcribe_batched(self, audio_path: str, language: Optional[str] = None):
        """Enhanced batched inference with optimizations"""
        logger.debug("📦 Using enhanced batched inference pipeline")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.batched_pipeline.transcribe(
                audio_path,
                batch_size=config.BATCH_SIZE,
                language=language,
                task="transcribe",
                beam_size=config.WHISPER_BEAM_SIZE,
                temperature=config.TEMPERATURE,
                condition_on_previous_text=config.CONDITION_ON_PREVIOUS_TEXT,
                vad_filter=config.VAD_ENABLED,
                # Enhanced VAD parameters for better real-time performance
                vad_parameters={
                    "threshold": 0.3,
                    "min_speech_duration_ms": 100,
                    "min_silence_duration_ms": 500
                } if config.VAD_ENABLED else None
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: Optional[str] = None):
        """Enhanced regular transcription with optimizations"""
        logger.debug("🎯 Using enhanced regular transcription")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.model.transcribe(
                audio_path,
                beam_size=config.WHISPER_BEAM_SIZE,
                language=language,
                task="transcribe",
                temperature=config.TEMPERATURE,
                condition_on_previous_text=config.CONDITION_ON_PREVIOUS_TEXT,
                vad_filter=config.VAD_ENABLED,
                # Enhanced VAD parameters
                vad_parameters={
                    "threshold": 0.3,
                    "min_speech_duration_ms": 100,
                    "min_silence_duration_ms": 500
                } if config.VAD_ENABLED else None
            )
        )
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get detailed model information"""
        return {
            "model_name": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "last_used": self.last_used,
            "batched_inference": config.USE_BATCHED_INFERENCE,
            "dynamic_loading": config.DYNAMIC_MODEL_LOADING,
            "vad_enabled": config.VAD_ENABLED,
            "load_error": self.load_error
        }
    
    def cleanup(self):
        """Enhanced cleanup with better resource management"""
        if self.batched_pipeline:
            del self.batched_pipeline
            self.batched_pipeline = None
            
        if self.model:
            del self.model
            self.model = None
        
        # Enhanced GPU cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
        self.is_ready.clear()
        logger.info("🧯 Enhanced Whisper service cleaned up")

# Global enhanced service instance
whisper_service = EnhancedWhisperService()
