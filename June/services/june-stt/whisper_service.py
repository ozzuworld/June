"""
Simplified Faster-Whisper Service following best practices
Relies on faster-whisper built-in capabilities with minimal custom logic
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

from config import config

logger = logging.getLogger(__name__)

class SimplifiedWhisperService:
    """
    Simplified faster-whisper service following best practices:
    - Relies on faster-whisper built-in silence removal and VAD
    - Minimal custom filtering
    - Batched inference for throughput, regular for low latency
    - Uses library defaults unless specific issues observed
    """
    
    def __init__(self):
        self.model = None
        self.batched_pipeline = None
        self.is_ready = threading.Event()
        self.load_error = None
        
    async def initialize(self):
        """Initialize model with faster-whisper best practices"""
        if self.model:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"🎯 Loading faster-whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            logger.info(f"📦 Batched inference: {config.USE_BATCHED_INFERENCE}, VAD: {config.VAD_ENABLED}")
            logger.info(f"🎛️  RMS prefilter: {config.RMS_PREFILTER_ENABLED}, Language: {config.LANGUAGE or 'auto'}")
            
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._create_model)
            
            # Initialize batched pipeline if enabled (recommended for throughput)
            if config.USE_BATCHED_INFERENCE:
                logger.info("⚡ Initializing BatchedInferencePipeline...")
                self.batched_pipeline = BatchedInferencePipeline(model=self.model)
                logger.info("✅ Batched inference ready - includes built-in silence removal")
            
            self.is_ready.set()
            logger.info("🚀 Simplified faster-whisper service ready")
            
        except Exception as e:
            logger.error(f"❌ Model initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _create_model(self) -> WhisperModel:
        """Create model with optimized parameters"""
        return WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
            cpu_threads=config.WHISPER_CPU_THREADS if config.WHISPER_DEVICE == "cpu" else 0,
            num_workers=config.WHISPER_NUM_WORKERS,
            download_root=config.WHISPER_CACHE_DIR,
            local_files_only=False
        )
    
    def is_model_ready(self) -> bool:
        return self.is_ready.is_set() and self.model is not None
    
    def _optional_rms_check(self, audio_path: str) -> bool:
        """
        Optional RMS-based prefilter - only if explicitly enabled
        Most deployments should disable this and rely on faster-whisper's built-in capabilities
        """
        if not config.RMS_PREFILTER_ENABLED:
            return True  # Skip prefilter, let faster-whisper handle it
            
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
            return True  # Conservative: process if check fails
    
    def _minimal_noise_filter(self, text: str, segments: List) -> bool:
        """
        Minimal filtering for obvious noise - only filter clear artifacts
        Returns True if text should be kept
        """
        if not text or len(text.strip()) == 0:
            return False
        
        clean_text = text.lower().strip()
        
        # Only filter single non-alphabetic characters or obvious noise
        if len(clean_text) == 1 and not clean_text.isalpha():
            logger.debug(f"🗑️  Filtered single non-alphabetic: '{text}'")
            return False
        
        # Filter only if ALL segments are very short and low confidence (if available)
        if segments and len(segments) > 0:
            try:
                avg_length = sum(len(seg.text.strip()) for seg in segments) / len(segments)
                if avg_length <= 2 and len(clean_text) <= 3:
                    logger.debug(f"🗑️  Filtered very short low-content: '{text}'")
                    return False
            except:
                pass  # If segment analysis fails, keep the text
        
        return True
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Simplified transcription relying on faster-whisper built-in capabilities
        - Optional RMS prefilter (disabled by default)
        - Batched inference with built-in silence removal OR regular transcription
        - Minimal noise filtering only
        - Uses faster-whisper defaults for VAD and silence handling
        """
        if not self.is_model_ready():
            raise RuntimeError("Model not ready")
        
        start_time = time.time()
        
        try:
            # Optional RMS prefilter (disabled by default)
            if not self._optional_rms_check(audio_path):
                return {
                    "text": "",
                    "language": language or config.LANGUAGE or "en",
                    "language_probability": 0.0,
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "rms_prefilter"
                }

            # Use configured or provided language for better performance
            target_language = language or config.LANGUAGE
            
            # Choose transcription method
            if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                segments, info = await self._transcribe_batched(audio_path, target_language)
                method = "batched"
            else:
                segments, info = await self._transcribe_regular(audio_path, target_language)
                method = "regular"
            
            segment_list = list(segments)
            full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
            
            # Minimal noise filtering
            if not self._minimal_noise_filter(full_text, segment_list):
                return {
                    "text": "",
                    "language": getattr(info, 'language', target_language or "en"),
                    "language_probability": getattr(info, 'language_probability', 0.0),
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "noise_filter",
                    "method": method
                }
            
            processing_time = int((time.time() - start_time) * 1000)
            
            # Log segment details for debugging
            if segment_list and logger.isEnabledFor(logging.DEBUG):
                for i, seg in enumerate(segment_list[:3]):  # Log first 3 segments
                    logger.debug(f"  Segment {i}: {seg.start:.2f}-{seg.end:.2f}s: '{seg.text.strip()}'")
            
            logger.info(f"✅ Transcribed via {method} ({processing_time}ms): {full_text[:100]}{'...' if len(full_text) > 100 else ''}")
            
            return {
                "text": full_text,
                "language": getattr(info, 'language', target_language or "en"),
                "language_probability": getattr(info, 'language_probability', 0.0),
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
        """Batched inference - includes built-in silence removal in faster-whisper 1.2+"""
        logger.debug("📦 Using batched inference pipeline")
        
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
                # Use faster-whisper defaults for VAD - no custom parameters
                vad_filter=config.VAD_ENABLED
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: Optional[str] = None):
        """Regular transcription - uses faster-whisper built-in VAD defaults"""
        logger.debug("🎯 Using regular transcription")
        
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
                # Use faster-whisper defaults for VAD - no custom parameters
                vad_filter=config.VAD_ENABLED
            )
        )
    
    def cleanup(self):
        """Clean up resources"""
        if self.batched_pipeline:
            del self.batched_pipeline
            self.batched_pipeline = None
            
        if self.model:
            del self.model
            self.model = None
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        self.is_ready.clear()
        logger.info("🧹 Whisper service cleaned up")

# Global service instance
whisper_service = SimplifiedWhisperService()