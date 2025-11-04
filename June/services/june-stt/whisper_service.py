"""
WhisperX Service with Enhanced Features and Silero VAD Integration
Provides word-level timestamps, speaker diarization, and accent optimization
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
    """Enhanced WhisperX service with word-level timestamps and diarization"""
    
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
        
        # Accent optimization prompts
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
            
            # Load WhisperX model
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(None, self._load_whisperx_model)
            
            # Load alignment model for word-level timestamps
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
        """Load WhisperX transcription model with initial_prompt in asr_options"""
        # Build asr_options with initial_prompt if accent optimization is enabled
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
            asr_options=asr_options if asr_options else None
        )
    
    def _load_alignment_model(self):
        """Load alignment model for word-level timestamps"""
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
        """Use Silero VAD for intelligent speech detection"""
        if not config.SILERO_VAD_ENABLED or self.vad_model is None:
            # Fallback to RMS-based detection
            rms = np.sqrt(np.mean(audio ** 2)) if len(audio) > 0 else 0.0
            return rms > 0.001
        
        try:
            if len(audio) == 0:
                return False
                
            # Convert to tensor
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
                return False
            
            # Calculate total speech duration
            total_speech_duration = sum(
                segment['end'] - segment['start'] for segment in speech_timestamps
            )
            
            # Require minimum speech content
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
        Enhanced transcription with WhisperX
        
        Features:
        - Word-level timestamps
        - Speaker diarization (optional)
        - Accent optimization via asr_options
        - Silero VAD preprocessing
        """
        if not self.is_model_ready():
            raise RuntimeError("WhisperX model not ready")
        
        start_time = time.time()
        
        try:
            async with self.model_lock:
                self._model_usage_count += 1
                
                # Preprocessing with Silero VAD
                if config.SILERO_VAD_ENABLED:
                    should_process = await self._vad_preprocess(audio_path)
                    if not should_process:
                        return {
                            "text": "",
                            "language": language or config.DEFAULT_LANGUAGE,
                            "processing_time_ms": int((time.time() - start_time) * 1000),
                            "segments": [],
                            "word_segments": [],
                            "skipped_reason": "no_speech_detected_by_silero_vad",
                            "method": "whisperx_silero_filtered"
                        }
                
                # Determine language
                optimal_language = self._get_optimal_language(language)
                
                # Load audio with WhisperX
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(
                    None,
                    whisperx.load_audio,
                    audio_path
                )
                
                # Transcribe with WhisperX (initial_prompt now handled in asr_options)
                logger.debug("Running WhisperX transcription...")
                result = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(
                        audio,
                        batch_size=config.BATCH_SIZE,
                        language=optimal_language if config.FORCE_LANGUAGE else None
                        # Note: initial_prompt is now set in asr_options during model loading
                    )
                )
                
                # Word-level alignment
                word_segments = []
                if return_word_timestamps and self.align_model:
                    logger.debug("Performing word-level alignment...")
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
                    
                    # Extract word-level timestamps
                    word_segments = self._extract_word_segments(result)
                
                # Speaker diarization (optional)
                speakers = None
                if enable_diarization and self.diarize_model:
                    logger.debug("Running speaker diarization...")
                    diarize_segments = await loop.run_in_executor(
                        None,
                        lambda: self.diarize_model(audio)
                    )
                    result = whisperx.assign_word_speakers(diarize_segments, result)
                    speakers = self._extract_speaker_info(result)
                
                # Build response
                full_text = " ".join([seg["text"].strip() for seg in result["segments"]]).strip()
                
                processing_time = int((time.time() - start_time) * 1000)
                
                response = {
                    "text": full_text,
                    "language": result.get("language", optimal_language),
                    "processing_time_ms": processing_time,
                    "method": "whisperx_enhanced",
                    "segments": [
                        {
                            "start": seg["start"],
                            "end": seg["end"],
                            "text": seg["text"].strip()
                        } for seg in result["segments"]
                    ]
                }
                
                # Add word-level timestamps if available
                if word_segments:
                    response["word_segments"] = word_segments
                    response["has_word_timestamps"] = True
                
                # Add speaker info if available
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
    
    async def _vad_preprocess(self, audio_path: str) -> bool:
        """Preprocess audio with Silero VAD to check for speech"""
        try:
            import soundfile as sf
            audio_data, sr = sf.read(audio_path)
            
            if not isinstance(audio_data, np.ndarray):
                audio_data = np.array(audio_data)
            
            # Convert to mono if needed
            if len(audio_data.shape) > 1:
                audio_data = audio_data.mean(axis=1)
            
            return self.has_speech_content(audio_data, sr)
            
        except Exception as e:
            logger.warning(f"VAD preprocessing error: {e}, proceeding with transcription")
            return True  # Proceed if VAD fails
    
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
                    "text": segment["text"].strip()
                })
        
        return speakers
    
    def _get_optimal_language(self, requested_language: Optional[str] = None) -> str:
        """Determine optimal language with accent handling"""
        if config.FORCE_LANGUAGE:
            return config.DEFAULT_LANGUAGE
        
        if requested_language:
            return requested_language
            
        return config.DEFAULT_LANGUAGE
    
    def _get_accent_prompt(self, language: str) -> str:
        """Get accent-optimized initial prompt (now handled in asr_options)"""
        # This method is kept for backward compatibility but initial_prompt
        # is now set in asr_options during model loading
        if not config.ACCENT_OPTIMIZATION:
            return ""
            
        if language == "en":
            return self.active_prompt
        
        return ""
    
    def set_accent_mode(self, mode: str = "latin"):
        """Set accent optimization mode (requires model reload to take effect)"""
        if mode in self.accent_prompts:
            self.active_prompt = self.accent_prompts[mode]
            logger.info(f"Accent mode set to '{mode}' - model reload required for changes to take effect")
            logger.warning("Note: To apply new accent prompt, the model needs to be reloaded")
        else:
            logger.warning(f"Unknown accent mode '{mode}', available: {list(self.accent_prompts.keys())}")
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get comprehensive model information"""
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
                "initial_prompt_in_asr_options": True,  # New approach
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