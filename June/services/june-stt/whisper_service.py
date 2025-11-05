"""
WhisperX Service - Properly Implemented
Uses WhisperX native features without redundant preprocessing
"""
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List
from pathlib import Path

import torch
import numpy as np
import whisperx
import gc

from config import config

logger = logging.getLogger(__name__)


class WhisperXService:
    """WhisperX service using native features - no redundant VAD"""
    
    def __init__(self):
        self.model = None
        self.align_model = None
        self.align_metadata = None
        self.diarize_model = None
        
        self.is_ready = threading.Event()
        self.load_error = None
        self.model_lock = asyncio.Lock()
        self.last_used = time.time()
        self._model_usage_count = 0
        
        # Determine device
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        
        # Fix cuDNN/TF32 issues
        if self.device == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        
        # HuggingFace token for diarization
        self.hf_token = os.getenv("HF_TOKEN", None)
        
        logger.info(f"WhisperX service initialized: device={self.device}, compute={self.compute_type}")
    
    async def initialize(self):
        """Initialize WhisperX model with proper configuration"""
        if self.model and not self.load_error:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"Loading WhisperX {config.WHISPER_MODEL} on {self.device}")
            
            loop = asyncio.get_event_loop()
            
            # Load WhisperX model with VAD options
            self.model = await loop.run_in_executor(None, self._load_whisperx_model)
            
            # Preload alignment model for word-level timestamps
            if config.ENABLE_WORD_TIMESTAMPS:
                logger.info("Loading alignment model for word-level timestamps...")
                self.align_model, self.align_metadata = await loop.run_in_executor(
                    None, 
                    self._load_alignment_model
                )
            
            # Optional: Load diarization model
            if config.DIARIZATION_ENABLED and self.hf_token:
                logger.info("Loading speaker diarization model...")
                self.diarize_model = await loop.run_in_executor(
                    None,
                    self._load_diarization_model
                )
            
            self.is_ready.set()
            self.last_used = time.time()
            
            logger.info("✅ WhisperX service fully initialized")
            logger.info(f"   - Model: {config.WHISPER_MODEL}")
            logger.info(f"   - Alignment: {'✓' if self.align_model else '✗'}")
            logger.info(f"   - Diarization: {'✓' if self.diarize_model else '✗'}")
            logger.info(f"   - Built-in VAD: ✓ (native WhisperX)")
            
        except Exception as e:
            logger.error(f"WhisperX initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _load_whisperx_model(self):
        """Load WhisperX model with proper VAD configuration"""
        # WhisperX load_model parameters
        asr_options = {
            "beam_size": config.WHISPER_BEAM_SIZE,
            "best_of": 5,
            "patience": 1.0,
            "length_penalty": 1.0,
            "suppress_tokens": [-1],
            "suppress_blank": True,
            "without_timestamps": False,
        }
        
        # Add initial prompt for accent optimization
        if config.ACCENT_OPTIMIZATION and config.INITIAL_PROMPT:
            asr_options["initial_prompt"] = config.INITIAL_PROMPT
            logger.info(f"Using accent prompt: {config.INITIAL_PROMPT[:80]}...")
        
        # VAD options for WhisperX's built-in VAD
        vad_options = {
            "vad_onset": 0.500,  # Higher = more conservative (less false positives)
            "vad_offset": 0.363,  # Speech end threshold
        }
        
        return whisperx.load_model(
            config.WHISPER_MODEL,
            device=self.device,
            compute_type=self.compute_type,
            download_root=config.WHISPER_CACHE_DIR,
            language=config.DEFAULT_LANGUAGE if config.FORCE_LANGUAGE else None,
            asr_options=asr_options,
            vad_options=vad_options,
        )
    
    def _load_alignment_model(self):
        """Load alignment model for word-level timestamps"""
        language = config.DEFAULT_LANGUAGE if config.FORCE_LANGUAGE else "en"
        return whisperx.load_align_model(
            language_code=language,
            device=self.device
        )
    
    def _load_diarization_model(self):
        """Load speaker diarization model"""
        try:
            return whisperx.DiarizationPipeline(
                use_auth_token=self.hf_token,
                device=self.device
            )
        except Exception as e:
            logger.warning(f"Diarization model loading failed: {e}")
            return None
    
    def is_model_ready(self) -> bool:
        """Check if model is ready"""
        return self.is_ready.is_set() and self.model is not None and not self.load_error
    
    def has_speech_content(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        Simple RMS-based speech detection for pre-filtering
        WhisperX's built-in VAD handles the real detection
        """
        if len(audio) == 0:
            return False
        
        # Simple energy-based check
        rms = np.sqrt(np.mean(audio ** 2))
        
        # Very low threshold - just filter complete silence
        return rms > 0.0005
    
    async def transcribe(
        self, 
        audio_path: str, 
        language: Optional[str] = None,
        return_word_timestamps: bool = True,
        enable_diarization: bool = False
    ) -> Dict[str, Any]:
        """
        Transcribe audio using WhisperX with native VAD
        """
        if not self.is_model_ready():
            raise RuntimeError("WhisperX model not ready")
        
        start_time = time.time()
        
        try:
            async with self.model_lock:
                self._model_usage_count += 1
                
                # Determine language
                optimal_language = self._get_optimal_language(language)
                
                # Load audio via WhisperX utility
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(
                    None,
                    whisperx.load_audio,
                    audio_path
                )
                
                # Check if audio has any content before processing
                if not self.has_speech_content(audio):
                    return {
                        "text": "",
                        "language": optimal_language,
                        "processing_time_ms": int((time.time() - start_time) * 1000),
                        "method": "whisperx_native",
                        "segments": [],
                        "filtered": "no_speech_content"
                    }
                
                # Transcribe using WhisperX with built-in VAD
                logger.debug("Running WhisperX transcription with native VAD...")
                result = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(
                        audio,
                        batch_size=config.BATCH_SIZE,
                        language=optimal_language if config.FORCE_LANGUAGE else None,
                    )
                )
                
                # Handle "no active speech" case from WhisperX VAD
                if not result.get("segments"):
                    logger.info("WhisperX VAD: No active speech detected")
                    return {
                        "text": "",
                        "language": optimal_language,
                        "processing_time_ms": int((time.time() - start_time) * 1000),
                        "method": "whisperx_native",
                        "segments": [],
                        "filtered": "whisperx_vad_no_speech"
                    }
                
                # Optional word-level alignment
                word_segments = []
                if return_word_timestamps and self.align_model and result.get("segments"):
                    logger.debug("Performing word-level alignment...")
                    try:
                        result = await loop.run_in_executor(
                            None,
                            lambda: whisperx.align(
                                result["segments"],
                                self.align_model,
                                self.align_metadata,
                                audio,
                                self.device,
                                return_char_alignments=False
                            )
                        )
                        word_segments = self._extract_word_segments(result)
                    except Exception as e:
                        logger.warning(f"Alignment failed: {e}, continuing without word timestamps")
                
                # Optional speaker diarization
                speakers = None
                if enable_diarization and self.diarize_model and result.get("segments"):
                    logger.debug("Running speaker diarization...")
                    try:
                        diarize_segments = await loop.run_in_executor(
                            None,
                            lambda: self.diarize_model(audio)
                        )
                        result = whisperx.assign_word_speakers(diarize_segments, result)
                        speakers = self._extract_speaker_info(result)
                    except Exception as e:
                        logger.warning(f"Diarization failed: {e}, continuing without speaker info")
                
                # Build response
                segs = result.get("segments", [])
                full_text = " ".join([seg.get("text", "").strip() for seg in segs]).strip()
                processing_time = int((time.time() - start_time) * 1000)
                
                response = {
                    "text": full_text,
                    "language": result.get("language", optimal_language),
                    "processing_time_ms": processing_time,
                    "method": "whisperx_native",
                    "segments": [
                        {
                            "start": seg.get("start"),
                            "end": seg.get("end"),
                            "text": seg.get("text", "").strip()
                        } for seg in segs
                    ]
                }
                
                if word_segments:
                    response["word_segments"] = word_segments
                    response["has_word_timestamps"] = True
                
                if speakers:
                    response["speakers"] = speakers
                    response["has_diarization"] = True
                
                # Cleanup
                del audio
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()
                
                return response
                
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"WhisperX transcription failed after {processing_time}ms: {e}")
            raise
    
    def _extract_word_segments(self, aligned_result: Dict) -> List[Dict]:
        """Extract word-level timestamps from aligned result"""
        word_segments = []
        for segment in aligned_result.get("segments", []):
            for word_info in segment.get("words", []):
                word_segments.append({
                    "word": word_info.get("word", ""),
                    "start": word_info.get("start", 0.0),
                    "end": word_info.get("end", 0.0),
                    "score": word_info.get("score", 1.0)
                })
        return word_segments
    
    def _extract_speaker_info(self, diarized_result: Dict) -> List[Dict]:
        """Extract speaker information from diarized result"""
        speakers = []
        for segment in diarized_result.get("segments", []):
            if "speaker" in segment:
                speakers.append({
                    "speaker": segment["speaker"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": segment.get("text", "").strip()
                })
        return speakers
    
    def _get_optimal_language(self, requested_language: Optional[str] = None) -> str:
        """Determine optimal language for transcription"""
        if config.FORCE_LANGUAGE:
            return config.DEFAULT_LANGUAGE
        if requested_language:
            return requested_language
        return config.DEFAULT_LANGUAGE
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        model_size_map = {
            "tiny": "39M", "base": "74M", "small": "244M", "medium": "769M",
            "large": "1.5B", "large-v2": "1.5B", "large-v3": "1.5B", "large-v3-turbo": "809M"
        }
        
        return {
            "framework": "whisperx",
            "whisper_model": config.WHISPER_MODEL,
            "model_size": model_size_map.get(config.WHISPER_MODEL, "unknown"),
            "device": self.device,
            "compute_type": self.compute_type,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "features": {
                "native_vad": "whisperx_built_in",
                "word_level_timestamps": self.align_model is not None,
                "speaker_diarization": self.diarize_model is not None,
                "accent_optimization": config.ACCENT_OPTIMIZATION,
            },
            "language_forcing": config.FORCE_LANGUAGE,
            "default_language": config.DEFAULT_LANGUAGE,
        }
    
    async def cleanup(self):
        """Cleanup models and free memory"""
        logger.info("Cleaning up WhisperX models...")
        if self.model:
            del self.model
            self.model = None
        if self.align_model:
            del self.align_model
            self.align_model = None
        if self.diarize_model:
            del self.diarize_model
            self.diarize_model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        self.is_ready.clear()
        logger.info("✅ WhisperX cleanup complete")


# Global service instance
whisper_service = WhisperXService()
