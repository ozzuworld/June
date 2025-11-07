#!/usr/bin/env python3
"""
Whisper-Streaming Service - Real-Time Transcription
Implements UFAL whisper_streaming with faster-whisper backend
Achieves 3.3s average latency vs 15s+ with WhisperX batching
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any
import numpy as np

try:
    from whisper_online import FasterWhisperASR, OnlineASRProcessor
except ImportError:
    raise ImportError(
        "whisper_streaming not installed. Run: "
        "pip install git+https://github.com/ufal/whisper_streaming"
    )

from config import config

logger = logging.getLogger(__name__)


class WhisperStreamingService:
    """
    Real-time streaming transcription using UFAL whisper-streaming
    with LocalAgreement-n policy for low-latency transcription
    """
    
    def __init__(self):
        self.asr_backend = None
        self.is_ready = threading.Event()
        self.load_error = None
        self.model_lock = asyncio.Lock()
        self._model_usage_count = 0
        
        # Streaming processors per participant
        self.processors: Dict[str, OnlineASRProcessor] = {}
        
        logger.info("WhisperStreaming service initialized")
    
    async def initialize(self):
        """Initialize Whisper-Streaming backend"""
        if self.asr_backend and not self.load_error:
            return
        
        try:
            logger.info(f"Loading whisper-streaming with {config.WHISPER_MODEL}")
            
            loop = asyncio.get_event_loop()
            self.asr_backend = await loop.run_in_executor(None, self._load_backend)
            
            # Enable VAD (Voice Activity Controller)
            self.asr_backend.use_vad()
            logger.info("✅ VAC (Voice Activity Controller) enabled")
            
            self.is_ready.set()
            logger.info("✅ Whisper-Streaming service ready")
            logger.info(f"   - Model: {config.WHISPER_MODEL}")
            logger.info(f"   - Backend: faster-whisper")
            logger.info(f"   - VAD: Silero VAD (built-in)")
            logger.info(f"   - Expected latency: ~3.3 seconds")
            
        except Exception as e:
            logger.error(f"Whisper-Streaming initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _load_backend(self):
        """Load faster-whisper backend for whisper-streaming"""
        lan = config.DEFAULT_LANGUAGE if config.FORCE_LANGUAGE else "en"
        
        # FasterWhisperASR(language, model_size, compute_type, device)
        asr = FasterWhisperASR(
            lan=lan,
            modelsize=config.WHISPER_MODEL,
            cache_dir=config.WHISPER_CACHE_DIR,
        )
        
        return asr
    
    def is_model_ready(self) -> bool:
        """Check if model is ready"""
        return self.is_ready.is_set() and self.asr_backend is not None
    
    def create_processor(self, participant_id: str) -> OnlineASRProcessor:
        """
        Create a new OnlineASRProcessor for a participant
        
        Args:
            participant_id: Unique participant identifier
            
        Returns:
            OnlineASRProcessor configured for real-time streaming
        """
        if not self.is_model_ready():
            raise RuntimeError("Whisper-Streaming backend not ready")
        
        # Create processor with LocalAgreement policy
        processor = OnlineASRProcessor(
            self.asr_backend,
            buffer_trimming="segment",  # Trim at segment boundaries
            buffer_trimming_sec=15.0,    # Max 15s buffer (Whisper's 30s window)
        )
        
        processor.init()  # Initialize processor state
        self.processors[participant_id] = processor
        
        logger.info(f"✅ Created streaming processor for {participant_id}")
        return processor
    
    def get_processor(self, participant_id: str) -> Optional[OnlineASRProcessor]:
        """Get existing processor for participant"""
        return self.processors.get(participant_id)
    
    def remove_processor(self, participant_id: str):
        """Remove processor when participant disconnects"""
        if participant_id in self.processors:
            del self.processors[participant_id]
            logger.info(f"🗑️  Removed processor for {participant_id}")
    
    async def process_audio_chunk(
        self,
        participant_id: str,
        audio_chunk: np.ndarray,
    ) -> Optional[str]:
        """
        Process audio chunk for real-time transcription
        
        Args:
            participant_id: Participant identifier
            audio_chunk: Float32 numpy array, 16kHz mono
            
        Returns:
            Confirmed transcript text (if any), or None
        """
        if not self.is_model_ready():
            return None
        
        # Get or create processor for this participant
        processor = self.get_processor(participant_id)
        if not processor:
            processor = self.create_processor(participant_id)
        
        try:
            # Insert audio chunk
            processor.insert_audio_chunk(audio_chunk)
            
            # Process and get confirmed output (LocalAgreement-2)
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                processor.process_iter
            )
            
            # output is tuple: (beg_timestamp, end_timestamp, text)
            # Return only if we have confirmed text
            if output:
                _, _, text = output
                text = text.strip()
                if text:
                    self._model_usage_count += 1
                    return text
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing audio for {participant_id}: {e}")
            return None
    
    async def finish_utterance(self, participant_id: str) -> Optional[str]:
        """
        Finish current utterance and get final output
        Call this when participant disconnects or stops speaking
        
        Args:
            participant_id: Participant identifier
            
        Returns:
            Final transcript text
        """
        processor = self.get_processor(participant_id)
        if not processor:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(None, processor.finish)
            
            # Re-initialize for next utterance
            processor.init()
            
            if output:
                _, _, text = output
                return text.strip()
            
            return None
            
        except Exception as e:
            logger.error(f"Error finishing utterance for {participant_id}: {e}")
            return None
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        return {
            "framework": "whisper-streaming",
            "backend": "faster-whisper",
            "whisper_model": config.WHISPER_MODEL,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "active_processors": len(self.processors),
            "features": {
                "real_time_streaming": True,
                "vad": "silero_vad",
                "policy": "LocalAgreement-2",
                "buffer_trimming": "segment",
                "expected_latency_sec": 3.3,
            },
            "language": config.DEFAULT_LANGUAGE,
        }
    
    async def cleanup(self):
        """Cleanup processors and models"""
        logger.info("Cleaning up Whisper-Streaming service...")
        
        # Clear all processors
        self.processors.clear()
        
        if self.asr_backend:
            del self.asr_backend
            self.asr_backend = None
        
        self.is_ready.clear()
        logger.info("✅ Whisper-Streaming cleanup complete")


# Global service instance
whisper_streaming_service = WhisperStreamingService()
