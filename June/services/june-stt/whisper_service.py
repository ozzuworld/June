"""
Optimized Faster-Whisper Service following best practices
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List

import torch
from faster_whisper import WhisperModel

from config import config

logger = logging.getLogger(__name__)

class OptimizedWhisperService:
    """
    Simplified Faster-Whisper service following official best practices
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
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Optimized transcription with adjustable VAD settings
        """
        if not self.is_model_ready():
            raise RuntimeError("Model not ready")
        
        start_time = time.time()
        
        try:
            # Start without VAD to avoid dropping short/quiet speech
            vad_filter = False
            vad_parameters = None

            logger.info(f"Transcribing with optimized settings: beam_size={config.WHISPER_BEAM_SIZE}")
            
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
                    vad_parameters=vad_parameters
                )
            )
            
            segment_list = list(segments)
            full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
            
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
