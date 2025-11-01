"""
Enhanced Whisper Service with Silero VAD
Combines faster-whisper optimizations with intelligent speech detection
Replaces custom RMS-based logic with ML-powered VAD
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
    Enhanced Whisper service with Silero VAD integration:
    - Intelligent speech detection (replaces RMS thresholds)
    - Dynamic model loading for memory efficiency
    - Batch processing capabilities
    - Production-ready error handling
    """
    
    def __init__(self):
        self.model = None
        self.batched_pipeline = None
        self.is_ready = threading.Event()
        self.load_error = None
        self.model_lock = asyncio.Lock()
        self.last_used = time.time()
        self._model_usage_count = 0
        
        # Silero VAD components
        self.vad_model = None
        self.get_speech_timestamps = None
        
    async def initialize(self):
        """Initialize Whisper model and Silero VAD"""
        if self.model and not self.load_error:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"🎯 Loading Enhanced Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            logger.info(f"📦 Features: Batched={config.USE_BATCHED_INFERENCE}, Silero VAD={config.SILERO_VAD_ENABLED}")
            
            # Initialize Whisper model
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._create_whisper_model)
            
            # Initialize batched pipeline if enabled
            if config.USE_BATCHED_INFERENCE:
                logger.info("⚡ Initializing BatchedInferencePipeline...")
                self.batched_pipeline = BatchedInferencePipeline(model=self.model)
                logger.info("✅ Batched inference ready")
            
            # Initialize Silero VAD
            if config.SILERO_VAD_ENABLED:
                await self._initialize_silero_vad()
            
            self.is_ready.set()
            self.last_used = time.time()
            logger.info("🚀 Enhanced Whisper + Silero VAD service ready")
            
        except Exception as e:
            logger.error(f"❌ Enhanced model initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    async def _initialize_silero_vad(self):
        """Initialize Silero VAD model"""
        try:
            logger.info("🎯 Loading Silero VAD for intelligent speech detection...")
            
            loop = asyncio.get_event_loop()
            vad_model, utils = await loop.run_in_executor(
                None,
                lambda: torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False,
                    verbose=False
                )
            )
            
            self.vad_model = vad_model
            self.get_speech_timestamps = utils[0]
            self.vad_model.eval()
            
            # Set optimal threading for real-time performance
            torch.set_num_threads(2)
            
            logger.info("✅ Silero VAD ready - will intelligently filter non-speech audio")
            
        except Exception as e:
            logger.error(f"❌ Silero VAD initialization failed: {e}")
            logger.info("⚠️ Continuing without Silero VAD (will use fallback detection)")
            config.SILERO_VAD_ENABLED = False
    
    def _create_whisper_model(self) -> WhisperModel:
        """Create Whisper model with optimal configuration"""
        compute_type = config.WHISPER_COMPUTE_TYPE
        
        # Optimize compute type based on device
        if config.WHISPER_DEVICE == "cpu":
            compute_type = "int8"
        elif config.WHISPER_DEVICE == "cuda" and torch.cuda.is_available():
            compute_type = "float16" if torch.cuda.get_device_capability()[0] >= 7 else "float32"
            
        logger.info(f"🔧 Creating Whisper model: {config.WHISPER_MODEL} ({compute_type} on {config.WHISPER_DEVICE})")
        
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
        """Check if models are ready for inference"""
        return self.is_ready.is_set() and self.model is not None and not self.load_error
    
    def has_speech_content(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        Intelligent speech detection using Silero VAD
        Replaces custom RMS-based logic with ML-powered detection
        """
        if not config.SILERO_VAD_ENABLED or self.vad_model is None:
            # Simple fallback: basic energy check
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001  # Very low threshold as fallback
        
        try:
            # Ensure audio is the right type and shape
            if len(audio) == 0:
                return False
                
            # Convert to torch tensor (required by Silero)
            audio_tensor = torch.from_numpy(audio.astype(np.float32))
            
            # Get speech timestamps
            speech_timestamps = self.get_speech_timestamps(
                audio_tensor,
                self.vad_model,
                sampling_rate=sample_rate,
                threshold=config.SILERO_VAD_THRESHOLD,
                min_speech_duration_ms=config.SILERO_MIN_SPEECH_MS,
                min_silence_duration_ms=config.SILERO_MIN_SILENCE_MS,
                return_seconds=True
            )
            
            if not speech_timestamps:
                logger.debug("🔇 Silero VAD: No speech detected")
                return False
            
            # Calculate total speech duration
            total_speech_duration = sum(
                segment['end'] - segment['start'] for segment in speech_timestamps
            )
            
            # Require meaningful speech duration
            min_required_speech = config.MIN_UTTERANCE_SEC * 0.6  # 60% of min utterance
            has_speech = total_speech_duration >= min_required_speech
            
            if has_speech:
                logger.debug(f"🎯 Silero VAD: Speech detected ({total_speech_duration:.2f}s)")
            else:
                logger.debug(f"🔇 Silero VAD: Insufficient speech ({total_speech_duration:.2f}s < {min_required_speech:.2f}s)")
                
            return has_speech
            
        except Exception as e:
            logger.warning(f"⚠️ Silero VAD error: {e}, using fallback")
            # Fallback to basic energy detection
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
    
    def _update_usage(self):
        """Update model usage statistics"""
        self.last_used = time.time()
        self._model_usage_count += 1
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Enhanced transcription with Silero VAD pre-filtering
        Only processes audio that contains actual speech
        """
        if not self.is_model_ready():
            if config.DYNAMIC_MODEL_LOADING:
                await self.initialize()
            else:
                raise RuntimeError("Enhanced Whisper model not ready")
        
        self._update_usage()
        start_time = time.time()
        
        try:
            async with self.model_lock:
                # Pre-filter with Silero VAD for file-based transcription
                if config.SILERO_VAD_ENABLED:
                    # Load audio for VAD check
                    import soundfile as sf
                    audio_data, sr = sf.read(audio_path)
                    if not isinstance(audio_data, np.ndarray):
                        audio_data = np.array(audio_data)
                    
                    # Convert to mono if stereo
                    if len(audio_data.shape) > 1:
                        audio_data = audio_data.mean(axis=1)
                    
                    # Check if audio contains speech
                    if not self.has_speech_content(audio_data, sr):
                        return {
                            "text": "",
                            "language": language or config.LANGUAGE or "en",
                            "language_probability": 0.0,
                            "processing_time_ms": int((time.time() - start_time) * 1000),
                            "segments": [],
                            "skipped_reason": "no_speech_detected_by_silero_vad",
                            "method": "silero_filtered"
                        }

                # Use configured language for better performance
                target_language = language or config.LANGUAGE
                
                # Choose transcription method
                if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                    segments, info = await self._transcribe_batched(audio_path, target_language)
                    method = "batched_with_silero_vad"
                else:
                    segments, info = await self._transcribe_regular(audio_path, target_language)
                    method = "regular_with_silero_vad"
                
                segment_list = list(segments)
                full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
                
                # Minimal post-processing (Silero already filtered out non-speech)
                if not full_text or len(full_text.strip()) < 2:
                    return {
                        "text": "",
                        "language": getattr(info, 'language', target_language or "en"),
                        "language_probability": getattr(info, 'language_probability', 0.0),
                        "processing_time_ms": int((time.time() - start_time) * 1000),
                        "segments": [],
                        "skipped_reason": "empty_transcription",
                        "method": method
                    }
                
                processing_time = int((time.time() - start_time) * 1000)
                
                logger.info(f"✅ Transcribed via {method} ({processing_time}ms): {full_text[:100]}{'...' if len(full_text) > 100 else ''}")
                
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
        """Batched inference with VAD optimization"""
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
                vad_filter=True,  # Enable Whisper's built-in VAD as secondary filter
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: Optional[str] = None):
        """Regular transcription with VAD optimization"""
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
                vad_filter=True,  # Enable Whisper's built-in VAD as secondary filter
            )
        )
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get comprehensive model information"""
        return {
            "whisper_model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "last_used": self.last_used,
            "batched_inference": config.USE_BATCHED_INFERENCE,
            "dynamic_loading": config.DYNAMIC_MODEL_LOADING,
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "silero_vad_ready": self.vad_model is not None,
            "load_error": self.load_error
        }
    
    def cleanup(self):
        """Enhanced cleanup with VAD model cleanup"""
        # Cleanup Silero VAD
        if self.vad_model is not None:
            del self.vad_model
            self.vad_model = None
        if self.get_speech_timestamps is not None:
            self.get_speech_timestamps = None
            
        # Cleanup Whisper models
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
        logger.info("🧯 Enhanced Whisper + Silero VAD service cleaned up")

# Global enhanced service instance
whisper_service = EnhancedWhisperService()
