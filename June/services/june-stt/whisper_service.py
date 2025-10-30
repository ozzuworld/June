"""
Optimized Faster-Whisper Service with silence detection to prevent false transcriptions
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List

import torch
import numpy as np
from faster_whisper import WhisperModel

from config import config

logger = logging.getLogger(__name__)

class OptimizedWhisperService:
    """
    Faster-Whisper service with silence detection to prevent "You" loop from silent audio
    """
    
    def __init__(self):
        self.model = None
        self.is_ready = threading.Event()
        self.load_error = None
        self._lock = threading.Lock()
        
    async def initialize(self):
        """Initialize model with optimized settings"""
        if self.model:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"Loading Faster-Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            logger.info(f"Using optimized compute_type: {config.WHISPER_COMPUTE_TYPE}")
            
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, 
                self._create_model
            )
            
            self.is_ready.set()
            logger.info("✅ Faster-Whisper model ready")
            
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
            local_files_only=False  # Allow downloads for first run
        )
    
    def is_model_ready(self) -> bool:
        return self.is_ready.is_set() and self.model is not None
    
    def _has_speech_activity(self, audio_path: str) -> bool:
        """
        Simple silence detection to prevent transcribing empty audio
        Returns True if audio contains potential speech activity
        """
        try:
            import soundfile as sf
            audio, sr = sf.read(audio_path)
            
            # Convert to numpy array if needed
            if not isinstance(audio, np.ndarray):
                audio = np.array(audio)
            
            # Calculate RMS energy
            rms = np.sqrt(np.mean(audio ** 2))
            
            # Calculate zero-crossing rate (speech typically has higher ZCR than silence)
            zero_crossings = np.sum(np.abs(np.diff(np.sign(audio)))) / (2 * len(audio))
            
            # Thresholds to detect actual speech vs silence/noise
            rms_threshold = 0.001  # Minimum RMS energy
            zcr_threshold = 0.01   # Minimum zero-crossing rate
            
            has_energy = rms > rms_threshold
            has_variation = zero_crossings > zcr_threshold
            
            logger.debug(f"Speech detection: RMS={rms:.6f}, ZCR={zero_crossings:.6f}, "
                        f"has_energy={has_energy}, has_variation={has_variation}")
            
            return has_energy and has_variation
            
        except Exception as e:
            logger.warning(f"Speech activity detection failed: {e}")
            # If detection fails, process the audio (conservative approach)
            return True
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Transcription with silence detection to prevent "You" loop
        """
        if not self.is_model_ready():
            raise RuntimeError("Model not ready")
        
        start_time = time.time()
        
        try:
            # Check if audio contains speech before processing
            if not self._has_speech_activity(audio_path):
                logger.info("🔇 No speech activity detected, skipping transcription")
                return {
                    "text": "",
                    "language": language or "en",
                    "language_probability": 0.0,
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "no_speech_activity"
                }

            # Enable VAD in Whisper for additional filtering
            vad_filter = True
            vad_parameters = {
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 100
            }

            logger.info(f"Transcribing with VAD enabled: beam_size={config.WHISPER_BEAM_SIZE}")
            
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None,
                lambda: self.model.transcribe(
                    audio_path,
                    beam_size=config.WHISPER_BEAM_SIZE,
                    language=language,
                    task="transcribe",
                    temperature=0.0,
                    vad_filter=vad_filter,
                    vad_parameters=vad_parameters,
                    condition_on_previous_text=False,  # Prevent hallucination
                    no_speech_threshold=0.6,           # Higher threshold to skip non-speech
                    logprob_threshold=-1.0,           # Skip low-confidence transcriptions
                    compression_ratio_threshold=2.4    # Skip repetitive audio
                )
            )
            
            segment_list = list(segments)
            full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
            
            # Filter out common false positives from silent audio
            if len(full_text) <= 2 or full_text.lower() in ['you', 'a', 'i', 'the', 'to', 'and', 'of', 'is', 'it']:
                logger.info(f"🚫 Filtering likely false positive: '{full_text}'")
                return {
                    "text": "",
                    "language": getattr(info, 'language', language),
                    "language_probability": getattr(info, 'language_probability', 0.0),
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "segments": [],
                    "skipped_reason": "likely_false_positive"
                }
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return {
                "text": full_text,
                "language": getattr(info, 'language', language),
                "language_probability": getattr(info, 'language_probability', 0.0),
                "processing_time_ms": processing_time,
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
    
    def cleanup(self):
        """Clean up resources"""
        if self.model:
            del self.model
            self.model = None
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        self.is_ready.clear()
        logger.info("✅ Whisper service cleaned up")

# Global service instance
whisper_service = OptimizedWhisperService()