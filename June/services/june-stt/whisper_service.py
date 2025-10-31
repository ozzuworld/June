"""
Modern Faster-Whisper v1.2.0 Service with batched inference and native VAD
Supports both regular and batched transcription with advanced silence handling
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List, Union

import torch
import numpy as np
from faster_whisper import WhisperModel, BatchedInferencePipeline

from config import config

logger = logging.getLogger(__name__)

class ModernWhisperService:
    """
    faster-whisper v1.2.0 service with batched inference and advanced VAD
    Features:
    - 4x faster batched inference
    - Native silence removal in batched mode
    - Advanced VAD with tuned parameters
    - RMS pre-filtering for efficiency
    - Improved false positive filtering
    """
    
    def __init__(self):
        self.model = None
        self.batched_pipeline = None
        self.is_ready = threading.Event()
        self.load_error = None
        self._lock = threading.Lock()
        
    async def initialize(self):
        """Initialize model with modern faster-whisper v1.2.0 features"""
        if self.model:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"Loading faster-whisper v1.2.0 - {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            logger.info(f"Batched inference: {config.USE_BATCHED_INFERENCE}, VAD: {config.VAD_ENABLED}")
            logger.info(f"Compute type: {config.WHISPER_COMPUTE_TYPE}, Batch size: {config.BATCH_SIZE}")
            
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, 
                self._create_model
            )
            
            # Initialize batched pipeline if enabled
            if config.USE_BATCHED_INFERENCE:
                logger.info("Initializing BatchedInferencePipeline for 4x speed boost...")
                self.batched_pipeline = BatchedInferencePipeline(model=self.model)
                logger.info("✅ Batched inference ready - 4x performance boost enabled")
            
            self.is_ready.set()
            logger.info("✅ faster-whisper v1.2.0 ready with modern features")
            
        except Exception as e:
            logger.error(f"❌ Model initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _create_model(self) -> WhisperModel:
        """Create model with optimized v1.2.0 parameters"""
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
    
    def _has_speech_activity(self, audio_path: str) -> bool:
        """
        RMS-based speech activity detection (first-line filter)
        Prevents wasting GPU on obviously silent audio
        """
        try:
            import soundfile as sf
            audio, sr = sf.read(audio_path)
            
            if not isinstance(audio, np.ndarray):
                audio = np.array(audio)
            
            # Calculate RMS energy
            rms = np.sqrt(np.mean(audio ** 2))
            
            # Calculate zero-crossing rate for speech characteristics
            zero_crossings = np.sum(np.abs(np.diff(np.sign(audio)))) / (2 * len(audio))
            
            # More permissive thresholds
            has_energy = rms > config.SILENCE_RMS_THRESHOLD
            has_variation = zero_crossings > 0.005  # Lowered from 0.01
            
            logger.debug(f"RMS gate: RMS={rms:.6f}, ZCR={zero_crossings:.6f}, "
                        f"energy={has_energy}, variation={has_variation}")
            
            return has_energy and has_variation
            
        except Exception as e:
            logger.warning(f"RMS speech detection failed: {e}")
            return True  # Conservative: process if detection fails
    
    def _filter_false_positives(self, text: str) -> bool:
        """
        Improved false positive filtering - less aggressive
        Returns True if text should be kept, False if filtered
        """
        if not text or len(text.strip()) <= 1:  # Only filter single characters
            return False
        
        clean_text = text.lower().strip()
        
        # Only filter very obvious false positives (not common words)
        obvious_false_positives = {
            # Audio artifacts
            'mmm', 'hmm', 'um', 'uh', 'ah', 'oh',
            # Very short meaningless sounds  
            'a', 'i', 'o', 'e',
            # Repeated characters
            'aa', 'ii', 'oo', 'ee'
        }
        
        # Don't filter common words anymore - they might be legitimate!
        if clean_text in obvious_false_positives:
            logger.info(f"🚫 Filtered obvious false positive: '{text}'")
            return False
        
        # Filter very short transcriptions that are likely noise
        if len(clean_text) <= 2 and clean_text not in ['ok', 'hi', 'no', 'go']:
            logger.info(f"🚫 Filtered very short noise: '{text}'")
            return False
            
        return True
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Modern transcription with faster-whisper v1.2.0 features
        - RMS pre-filtering
        - Batched inference (4x speed) or regular transcription
        - Native VAD with tuned parameters
        - Improved false positive filtering
        """
        if not self.is_model_ready():
            raise RuntimeError("Model not ready")
        
        start_time = time.time()
        
        try:
            # First-line filter: RMS-based speech detection
            if not self._has_speech_activity(audio_path):
                logger.info("🔇 No speech activity detected by RMS gate, skipping transcription")
                return {
                    "text": "",
                    "language": language or "en",
                    "language_probability": 0.0,
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "no_speech_activity_rms"
                }

            # Choose transcription method based on config
            if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                segments, info = await self._transcribe_batched(audio_path, language)
                method = "batched_4x_speed"
            else:
                segments, info = await self._transcribe_regular(audio_path, language)
                method = "regular"
            
            segment_list = list(segments)
            full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
            
            # Apply improved false positive filtering
            if not self._filter_false_positives(full_text):
                return {
                    "text": "",
                    "language": getattr(info, 'language', language),
                    "language_probability": getattr(info, 'language_probability', 0.0),
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "filtered_false_positive",
                    "method": method
                }
            
            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"✅ Transcribed via {method} ({processing_time}ms): {full_text[:100]}...")
            
            return {
                "text": full_text,
                "language": getattr(info, 'language', language),
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
            logger.error(f"Transcription failed after {processing_time}ms: {e}")
            raise
    
    async def _transcribe_batched(self, audio_path: str, language: Optional[str] = None):
        """Batched inference transcription (v1.1.0+ feature - 4x faster)"""
        logger.debug("Using batched inference pipeline")
        
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
                # Batched mode in v1.2.0 includes native silence removal
                vad_parameters=config.vad_parameters if config.VAD_ENABLED else None
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: Optional[str] = None):
        """Regular transcription with modern VAD parameters"""
        logger.debug("Using regular transcription with VAD")
        
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
                vad_parameters=config.vad_parameters if config.VAD_ENABLED else None
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
        logger.info("✅ Modern Whisper service cleaned up")

# Global service instance
whisper_service = ModernWhisperService()