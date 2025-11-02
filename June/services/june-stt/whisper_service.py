"""
Whisper Service with Silero VAD Integration and Accent Optimization
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
    """Whisper service with Silero VAD and accent optimization"""
    
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
        
        # Accent optimization
        self.accent_prompts = {
            "latin": "English speech with Latin accent. Mathematical terms: square root, calculations, numbers. Technical vocabulary: programming, computer, algorithm, function, variable.",
            "general": "Clear English speech with mathematical and technical vocabulary. Numbers, calculations, computer terms.",
            "technical": "Technical English discussion. Programming, mathematics, science, engineering terms. Clear pronunciation."
        }
        
        self.active_prompt = self.accent_prompts["latin"]
        
    async def initialize(self):
        """Initialize Whisper model and Silero VAD"""
        if self.model and not self.load_error:
            return
            
        try:
            os.makedirs(config.WHISPER_CACHE_DIR, exist_ok=True)
            
            logger.info(f"Loading Whisper {config.WHISPER_MODEL} on {config.WHISPER_DEVICE}")
            
            # Initialize Whisper model
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._create_whisper_model)
            
            # Initialize batched pipeline if enabled
            if config.USE_BATCHED_INFERENCE:
                logger.info("Initializing BatchedInferencePipeline")
                self.batched_pipeline = BatchedInferencePipeline(model=self.model)
            
            # Initialize Silero VAD
            if config.SILERO_VAD_ENABLED:
                await self._initialize_silero_vad()
            
            self.is_ready.set()
            self.last_used = time.time()
            
            logger.info("Whisper + Silero VAD service ready")
            
        except Exception as e:
            logger.error(f"Model initialization failed: {e}")
            self.load_error = str(e)
            raise
    
    async def _initialize_silero_vad(self):
        """Initialize Silero VAD model"""
        try:
            logger.info("Loading Silero VAD")
            
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
            
            logger.info("Silero VAD ready")
            
        except Exception as e:
            logger.error(f"Silero VAD initialization failed: {e}")
            logger.info("Continuing without Silero VAD")
            config.SILERO_VAD_ENABLED = False
    
    def _create_whisper_model(self) -> WhisperModel:
        """Create Whisper model with optimal configuration"""
        compute_type = config.WHISPER_COMPUTE_TYPE
        
        if config.WHISPER_DEVICE == "cpu":
            compute_type = "int8"
        elif config.WHISPER_DEVICE == "cuda" and torch.cuda.is_available():
            compute_type = "float16" if torch.cuda.get_device_capability()[0] >= 7 else "float32"
            
        logger.info(f"Creating Whisper model: {config.WHISPER_MODEL} ({compute_type} on {config.WHISPER_DEVICE})")
        
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
        """Silero VAD - Intelligent speech detection"""
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
    
    def _get_optimal_language(self, requested_language: Optional[str] = None) -> str:
        """Determine optimal language with accent handling"""
        if config.FORCE_LANGUAGE:
            return config.DEFAULT_LANGUAGE
        
        if requested_language:
            return requested_language
            
        return config.DEFAULT_LANGUAGE
    
    def _get_accent_prompt(self, language: str) -> str:
        """Get accent-optimized initial prompt"""
        if not config.ACCENT_OPTIMIZATION:
            return ""
            
        if language == "en":
            return self.active_prompt
        
        return ""
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Enhanced transcription with Silero VAD pre-filtering and accent optimization"""
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
                            "language": language or config.DEFAULT_LANGUAGE,
                            "processing_time_ms": int((time.time() - start_time) * 1000),
                            "segments": [],
                            "skipped_reason": "no_speech_detected_by_silero_vad",
                            "method": "silero_filtered"
                        }

                # Determine optimal language and prompt
                optimal_language = self._get_optimal_language(language)
                initial_prompt = self._get_accent_prompt(optimal_language)

                # Choose transcription method
                if config.USE_BATCHED_INFERENCE and self.batched_pipeline:
                    segments, info = await self._transcribe_batched(audio_path, optimal_language, initial_prompt)
                    method = "batched_enhanced"
                else:
                    segments, info = await self._transcribe_regular(audio_path, optimal_language, initial_prompt)
                    method = "regular_enhanced"
                
                segment_list = list(segments)
                full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
                
                processing_time = int((time.time() - start_time) * 1000)
                
                return {
                    "text": full_text,
                    "language": getattr(info, 'language', optimal_language),
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
    
    async def _transcribe_batched(self, audio_path: str, language: str, initial_prompt: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.batched_pipeline.transcribe(
                audio_path,
                batch_size=config.BATCH_SIZE,
                language=language,
                task="transcribe",
                vad_filter=True,
                initial_prompt=initial_prompt if initial_prompt else None,
                temperature=config.TEMPERATURE,
                beam_size=config.WHISPER_BEAM_SIZE,
                condition_on_previous_text=config.CONDITION_ON_PREVIOUS_TEXT,
            )
        )
    
    async def _transcribe_regular(self, audio_path: str, language: str, initial_prompt: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                vad_filter=True,
                initial_prompt=initial_prompt if initial_prompt else None,
                temperature=config.TEMPERATURE,
                beam_size=config.WHISPER_BEAM_SIZE,
                condition_on_previous_text=config.CONDITION_ON_PREVIOUS_TEXT,
            )
        )
    
    def set_accent_mode(self, mode: str = "latin"):
        """Set accent optimization mode"""
        if mode in self.accent_prompts:
            self.active_prompt = self.accent_prompts[mode]
            logger.info(f"Accent mode set to '{mode}'")
        else:
            logger.warning(f"Unknown accent mode '{mode}', available: {list(self.accent_prompts.keys())}")
    
    def get_model_info(self) -> Dict[str, Any]:
        model_size_map = {
            "tiny": "39M", "base": "74M", "small": "244M", "medium": "769M",
            "large": "1.5B", "large-v2": "1.5B", "large-v3": "1.5B", "large-v3-turbo": "809M"
        }
        
        return {
            "whisper_model": config.WHISPER_MODEL,
            "model_size": model_size_map.get(config.WHISPER_MODEL, "unknown"),
            "device": config.WHISPER_DEVICE,
            "is_ready": self.is_model_ready(),
            "usage_count": self._model_usage_count,
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "silero_vad_ready": self.vad_model is not None,
            "language_forcing": config.FORCE_LANGUAGE,
            "accent_optimization": config.ACCENT_OPTIMIZATION,
        }

whisper_service = EnhancedWhisperService()