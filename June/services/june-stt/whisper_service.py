"""
Whisper Service with Silero VAD Integration
Intelligent speech detection replacing custom RMS thresholds
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any

import torch
import numpy as np
from faster_whisper import WhisperModel, BatchedInferencePipeline

from config import config

logger = logging.getLogger(__name__)

class EnhancedWhisperService:
    """
    Whisper service with Silero VAD for intelligent speech detection
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
            
            logger.info(f"🎯 Loading Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
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
            logger.info("🚀 Whisper + Silero VAD service ready")
            
        except Exception as e:
            logger.error(f"❌ Model initialization failed: {e}")
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
            
            torch.set_num_threads(2)
            
            logger.info("✅ Silero VAD ready - intelligent speech detection enabled")
            
        except Exception as e:
            logger.error(f"❌ Silero VAD initialization failed: {e}")
            logger.info("⚠️ Continuing without Silero VAD")
            config.SILERO_VAD_ENABLED = False
    
    def _create_whisper_model(self) -> WhisperModel:
        """Create Whisper model with optimal configuration"""
        compute_type = config.WHISPER_COMPUTE_TYPE
        
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
        """Check if models are ready"""
        return self.is_ready.is_set() and self.model is not None and not self.load_error
    
    def has_speech_content(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        SILERO VAD - Intelligent speech detection
        Replaces custom RMS-based logic with ML-powered detection
        """
        if not config.SILERO_VAD_ENABLED or self.vad_model is None:
            # Simple fallback
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
        
        try:
            if len(audio) == 0:
                return False
                
            # Convert to torch tensor for Silero
            audio_tensor = torch.from_numpy(audio.astype(np.float32))
            
            # Get speech timestamps from Silero VAD
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
                return False
            
            # Calculate total speech duration
            total_speech_duration = sum(
                segment['end'] - segment['start'] for segment in speech_timestamps
            )
            
            # Require meaningful speech duration
            min_required_speech = config.MIN_UTTERANCE_SEC * 0.6
            has_speech = total_speech_duration >= min_required_speech
            
            if has_speech:
                logger.debug(f"🎯 Silero VAD: Speech detected ({total_speech_duration:.2f}s)")
            else:
                logger.debug(f"🔇 Silero VAD: Insufficient speech ({total_speech_duration:.2f}s)")
                
            return has_speech
            
        except Exception as e:
            logger.warning(f"⚠️ Silero VAD error: {e}, using fallback")
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Enhanced transcription with Silero VAD pre-filtering"""
        if not self.is_model_ready():
            raise RuntimeError("Whisper model not ready")
        
        start_time = time.time()
        
        try:
            async with self.model_lock:
                # Pre-filter with Silero VAD
                if config.SILERO_VAD_ENABLED:
                    import soundfile as sf
                    audio_data, sr = sf.read(audio_path)
                    if not isinstance(audio_data, np.ndarray):
                        audio_data = np.array(audio_data)
                    
                    if len(audio_data.shape) > 1:
                        audio_data = audio_data.mean(axis=1)
                    
                    if not self.has_speech_content(audio_data, sr):
                        return {
                            "text": "",
                            "language": language or "en",
                            "processing_time_ms": int((time.time() - start_time) * 1000),
                            "segments": [],
                            "skipped_reason": "no_speech_detected_by_silero_vad",
                            "method": "silero_filtered"
                        }

                # Choose transcription method
                if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                    segments, info = await self._transcribe_batched(audio_path, language)
                    method = "batched_with_silero_vad"
                else:
                    segments, info = await self._transcribe_regular(audio_path, language)
                    method = "regular_with_silero_vad"
                
                segment_list = list(segments)
                full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
                
                processing_time = int((time.time() - start_time) * 1000)
                
                return {
                    "text": full_text,
                    "language": getattr(info, 'language', language or "en"),
                    "processing_time_ms": processing_time,
                    "method": method,
                    "segments": [
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text.strip()
                        } for segment in segment_list
                    ]
                }
                
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"❌ Transcription failed after {processing_time}ms: {e}")
            raise
    
    async def _transcribe_batched(self, audio_path: str, language: Optional[str] = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.batched_pipeline.transcribe(
                audio_path,
                batch_size=config.BATCH_SIZE,
                language=language,
                task="transcribe",
                vad_filter=True
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: Optional[str] = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                vad_filter=True
            )
        )
    
    def get_model_info(self) -> Dict[str, Any]:
        return {
            "whisper_model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "silero_vad_ready": self.vad_model is not None
        }

# Global service instance
whisper_service = EnhancedWhisperService()
