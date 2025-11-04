"""
WhisperX Service with Enhanced Features and Silero VAD Integration
Provides word-level timestamps, speaker diarization, and accent optimization
(Pure WhisperX API usage)
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
    """Enhanced WhisperX service with word-level timestamps and diarization (pure WhisperX API)"""
    
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
        
        # Silero VAD components (for preprocessing)
        self.vad_model = None
        self.get_speech_timestamps = None
        
        # Determine device
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        
        # HuggingFace token for diarization (optional)
        self.hf_token = os.getenv("HF_TOKEN", None)
        
        logger.info(f"WhisperX service initialized: device={self.device}, compute={self.compute_type}")
        
        # Accent optimization prompts (used via asr_options at model load)
        self.accent_prompts = {
            "latin": "English speech with Latin accent. Mathematical terms: square root, calculations, numbers. Technical vocabulary: programming, computer, algorithm, function, variable.",
            "general": "Clear English speech with mathematical and technical vocabulary. Numbers, calculations, computer terms.",
            "technical": "Technical English discussion. Programming, mathematics, science, engineering terms. Clear pronunciation."
        }
        self.active_prompt = self.accent_prompts.get("latin", "")
    
    async def initialize(self):
        """Initialize WhisperX model, alignment model, and optional diarization"""
        if self.model and not self.load_error:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"Loading WhisperX {config.WHISPER_MODEL} on {self.device}")
            
            # Load WhisperX model (pure API)
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._load_whisperx_model)
            
            # Preload alignment model for word-level timestamps
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
            
            # Initialize Silero VAD for preprocessing
            if config.SILERO_VAD_ENABLED:
                await self._initialize_silero_vad()
            
            self.is_ready.set()
            self.last_used = time.time()
            
            logger.info("✅ WhisperX service fully initialized")
            logger.info(f"   - Model: {config.WHISPER_MODEL}")
            logger.info(f"   - Alignment: {'✓' if self.align_model else '✗'}")
            logger.info(f"   - Diarization: {'✓' if self.diarize_model else '✗'}")
            logger.info(f"   - Silero VAD: {'✓' if self.vad_model else '✗'}")
            
        except Exception as e:
            logger.error(f"WhisperX initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    def _load_whisperx_model(self):
        """Load WhisperX transcription model with asr_options for prompt-like behavior"""
        asr_options = {}
        if config.ACCENT_OPTIMIZATION and self.active_prompt:
            asr_options["initial_prompt"] = self.active_prompt
            logger.info(f"Using initial_prompt in asr_options: {self.active_prompt[:50]}...")
        
        return whisperx.load_model(
            config.WHISPER_MODEL,
            device=self.device,
            compute_type=self.compute_type,
            download_root=config.WHISPER_CACHE_DIR,
            language=config.DEFAULT_LANGUAGE if config.FORCE_LANGUAGE else None,
            asr_options=asr_options or None,
        )
    
    def _load_alignment_model(self):
        """Load alignment model for word-level timestamps"""
        # Language for alignment should match output language from transcribe; we preload with default
        language = config.DEFAULT_LANGUAGE if config.FORCE_LANGUAGE else "en"
        return whisperx.load_align_model(
            language_code=language,
            device=self.device
        )
    
    def _load_diarization_model(self):
        """Load speaker diarization model (requires HF token)"""
        try:
            return whisperx.DiarizationPipeline(
                use_auth_token=self.hf_token,
                device=self.device
            )
        except Exception as e:
            logger.warning(f"Diarization model loading failed: {e}")
            return None
    
    async def _initialize_silero_vad(self):
        """Initialize Silero VAD for speech detection preprocessing"""
        try:
            logger.info("Loading Silero VAD for preprocessing...")
            
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
            
            logger.info("✅ Silero VAD ready for preprocessing")
            
        except Exception as e:
            logger.error(f"Silero VAD initialization failed: {e}")
            logger.info("Continuing without Silero VAD preprocessing")
            config.SILERO_VAD_ENABLED = False
    
    def is_model_ready(self) -> bool:
        """Check if models are ready"""
        return self.is_ready.is_set() and self.model is not None and not self.load_error
    
    def has_speech_content(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """Use Silero VAD or fallback RMS-based detection"""
        if not config.SILERO_VAD_ENABLED or self.vad_model is None:
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
        
        try:
            if len(audio) == 0:
                return False
                
            audio_tensor = torch.from_numpy(audio.astype(np.float32))
            
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
            
            total_speech_duration = sum(
                segment['end'] - segment['start'] for segment in speech_timestamps
            )
            
            min_required_speech = config.MIN_UTTERANCE_SEC * 0.6
            has_speech = total_speech_duration >= min_required_speech
            
            return has_speech
            
        except Exception as e:
            logger.warning(f"Silero VAD error: {e}, using fallback")
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
    
    async def transcribe(
        self, 
        audio_path: str, 
        language: Optional[str] = None,
        return_word_timestamps: bool = True,
        enable_diarization: bool = False
    ) -> Dict[str, Any]:
        """
        Pure WhisperX transcription with optional alignment and diarization
        - load_audio -> model.transcribe(audio) -> align (optional)
        """
        if not self.is_model_ready():
            raise RuntimeError("WhisperX model not ready")
        
        start_time = time.time()
        
        try:
            async with self.model_lock:
                self._model_usage_count += 1
                
                # Determine language
                optimal_language = self._get_optimal_language(language)
                
                # Load audio via WhisperX utility (ensures expected format)
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(
                    None,
                    whisperx.load_audio,
                    audio_path
                )
                
                # Transcribe using pure WhisperX API
                logger.debug("Running WhisperX transcription (pure API)...")
                result = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(
                        audio,
                        batch_size=config.BATCH_SIZE,
                        language=optimal_language if config.FORCE_LANGUAGE else None,
                    )
                )
                
                # Optional word-level alignment
                word_segments = []
                if return_word_timestamps and self.align_model and result.get("segments"):
                    logger.debug("Performing word-level alignment (pure API)...")
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
                
                # Optional speaker diarization
                speakers = None
                if enable_diarization and self.diarize_model and result.get("segments"):
                    logger.debug("Running speaker diarization...")
                    diarize_segments = await loop.run_in_executor(
                        None,
                        lambda: self.diarize_model(audio)
                    )
                    result = whisperx.assign_word_speakers(diarize_segments, result)
                    speakers = self._extract_speaker_info(result)
                
                # Build response
                segs = result.get("segments", [])
                full_text = " ".join([seg.get("text", "").strip() for seg in segs]).strip()
                processing_time = int((time.time() - start_time) * 1000)
                
                response = {
                    "text": full_text,
                    "language": result.get("language", optimal_language),
                    "processing_time_ms": processing_time,
                    "method": "whisperx_pure",
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
        if config.FORCE_LANGUAGE:
            return config.DEFAULT_LANGUAGE
        if requested_language:
            return requested_language
        return config.DEFAULT_LANGUAGE
    
    def set_accent_mode(self, mode: str = "latin"):
        if mode in self.accent_prompts:
            self.active_prompt = self.accent_prompts[mode]
            logger.info(f"Accent mode set to '{mode}' - model reload required for changes to take effect")
        else:
            logger.warning(f"Unknown accent mode '{mode}', available: {list(self.accent_prompts.keys())}")
    
    def get_model_info(self) -> Dict[str, Any]:
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
                "word_level_timestamps": self.align_model is not None,
                "speaker_diarization": self.diarize_model is not None,
                "silero_vad_preprocessing": self.vad_model is not None,
                "accent_optimization": config.ACCENT_OPTIMIZATION,
            },
            "language_forcing": config.FORCE_LANGUAGE,
            "default_language": config.DEFAULT_LANGUAGE,
        }
    
    async def cleanup(self):
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
