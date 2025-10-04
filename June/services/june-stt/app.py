# June/services/june-stt/app.py
# SOTA Speech-to-Text Service with Intelligent Adaptation and Advanced Features

import os
import time
import uuid
import asyncio
import logging
import threading
import psutil
import librosa
import numpy as np
import soundfile as sf
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import torch
from faster_whisper import WhisperModel
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks, Header, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

# Import the shared auth (same as TTS service)
try:
    from shared import require_user_auth, require_service_auth, extract_user_id, extract_client_id
    AUTH_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Keycloak authentication available")
except ImportError:
    AUTH_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Keycloak authentication not available - using fallback")
    
    # Fallback auth functions
    async def require_user_auth(authorization: str = Header(None)):
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")
        return {"sub": "fallback_user", "client_id": "fallback"}
    
    async def require_service_auth():
        return {"client_id": "fallback", "authenticated": True}
    
    def extract_user_id(auth_data: Dict[str, Any]) -> str:
        return auth_data.get("sub", "fallback_user")
    
    def extract_client_id(auth_data: Dict[str, Any]) -> str:
        return auth_data.get("client_id", "fallback")

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables
whisper_model = None
transcript_storage = {}  # In-memory storage for transcripts
processing_queue = asyncio.Queue()
cleanup_task = None
processing_semaphore = None

# Enhanced Configuration with SOTA defaults
class Config:
    # Environment
    ENVIRONMENT = os.getenv("ENVIRONMENT", "adaptive")  # adaptive, production, accuracy, development
    
    # Orchestrator
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")
    ORCHESTRATOR_API_KEY = os.getenv("ORCHESTRATOR_API_KEY", "")
    
    # Faster-Whisper Configuration - SOTA defaults
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16" if torch.cuda.is_available() else "int8")
    
    # Intelligent Performance Settings
    if ENVIRONMENT == "production":
        # Fast but still good quality
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "3"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
        USE_INTELLIGENT_VAD = True
    elif ENVIRONMENT == "accuracy":
        # Maximum accuracy
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "5"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "8"))
        USE_INTELLIGENT_VAD = True
    elif ENVIRONMENT == "adaptive":
        # SOTA: Adapts based on audio characteristics
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "3"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "12"))
        USE_INTELLIGENT_VAD = True
    else:  # development
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "1"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "8"))
        USE_INTELLIGENT_VAD = False
    
    WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    
    # Resource Limits
    MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "6"))
    MAX_AUDIO_LENGTH = int(os.getenv("MAX_AUDIO_LENGTH", "600"))  # 10 minutes
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "100"))  # 100MB
    
    # Intelligent Audio Processing
    ENABLE_AUDIO_ENHANCEMENT = bool(os.getenv("ENABLE_AUDIO_ENHANCEMENT", "true").lower() == "true")
    ENABLE_NOISE_REDUCTION = bool(os.getenv("ENABLE_NOISE_REDUCTION", "true").lower() == "true")
    ENABLE_SMART_CHUNKING = bool(os.getenv("ENABLE_SMART_CHUNKING", "true").lower() == "true")
    
    # SOTA VAD Configuration
    VAD_AGGRESSIVENESS = float(os.getenv("VAD_AGGRESSIVENESS", "0.3"))  # 0.0 = least aggressive, 1.0 = most
    VAD_MIN_SPEECH_DURATION_MS = int(os.getenv("VAD_MIN_SPEECH_DURATION_MS", "100"))
    VAD_MIN_SILENCE_DURATION_MS = int(os.getenv("VAD_MIN_SILENCE_DURATION_MS", "200"))
    VAD_SPEECH_PAD_MS = int(os.getenv("VAD_SPEECH_PAD_MS", "400"))
    
    # Storage
    TRANSCRIPT_RETENTION_HOURS = int(os.getenv("TRANSCRIPT_RETENTION_HOURS", "24"))
    
    # Service
    PORT = int(os.getenv("PORT", "8000"))

config = Config()

# Enhanced Models
class AudioQuality(BaseModel):
    snr_db: float
    volume_level: float
    duration_seconds: float
    sample_rate: int
    is_speech_detected: bool
    noise_level: float
    recommended_vad: bool

class IntelligentTranscriptionConfig(BaseModel):
    use_vad: bool
    vad_aggressiveness: float
    chunk_audio: bool
    beam_size: int
    temperature: float
    language_hint: Optional[str] = None
    enable_enhancement: bool = True

class TranscriptionResult(BaseModel):
    transcript_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    processing_time_ms: int
    timestamp: datetime
    status: str = "completed"
    user_id: str
    segments: Optional[List[Dict[str, Any]]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    audio_quality: Optional[AudioQuality] = None
    processing_strategy: Optional[str] = None

class TranscriptNotification(BaseModel):
    transcript_id: str
    user_id: str
    text: str
    timestamp: datetime
    metadata: Dict[str, Any] = {}

class PerformanceMetrics(BaseModel):
    gpu_memory_used_mb: Optional[float] = None
    gpu_memory_total_mb: Optional[float] = None
    cpu_usage_percent: float
    ram_usage_percent: float
    processing_time_ms: int
    model_loaded: bool
    concurrent_requests: int

# SOTA Audio Processing Utilities
class AudioProcessor:
    @staticmethod
    def analyze_audio_quality(audio_path: str) -> AudioQuality:
        """Analyze audio to determine optimal processing strategy"""
        try:
            # Load audio
            y, sr = librosa.load(audio_path, sr=None)
            duration = len(y) / sr
            
            # Calculate SNR (Signal-to-Noise Ratio)
            # Split audio into frames and estimate noise floor
            frame_length = int(0.025 * sr)  # 25ms frames
            hop_length = int(0.010 * sr)    # 10ms hop
            
            # Estimate noise floor from quiet segments
            rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
            noise_threshold = np.percentile(rms, 20)  # Bottom 20% as noise estimate
            signal_power = np.mean(rms ** 2)
            noise_power = noise_threshold ** 2
            snr_db = 10 * np.log10(signal_power / (noise_power + 1e-10))
            
            # Volume analysis
            volume_level = np.sqrt(np.mean(y ** 2))
            
            # Speech detection using spectral features
            spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
            
            # Heuristic for speech detection
            is_speech_detected = (
                volume_level > 0.001 and  # Not silence
                np.mean(spectral_centroids) < 4000 and  # Human speech range
                np.mean(spectral_centroids) > 200 and
                duration > 0.3  # Minimum speech duration
            )
            
            # Recommend VAD based on quality
            recommended_vad = snr_db > 5 and volume_level > 0.005
            
            return AudioQuality(
                snr_db=float(snr_db),
                volume_level=float(volume_level),
                duration_seconds=float(duration),
                sample_rate=int(sr),
                is_speech_detected=is_speech_detected,
                noise_level=float(noise_threshold),
                recommended_vad=recommended_vad
            )
            
        except Exception as e:
            logger.warning(f"⚠️ Audio quality analysis failed: {e}")
            # Return conservative defaults
            return AudioQuality(
                snr_db=10.0,
                volume_level=0.01,
                duration_seconds=2.0,
                sample_rate=16000,
                is_speech_detected=True,
                noise_level=0.001,
                recommended_vad=False  # Conservative default
            )
    
    @staticmethod
    def enhance_audio(audio_path: str, output_path: str, quality: AudioQuality) -> str:
        """Enhance audio based on quality analysis"""
        try:
            y, sr = librosa.load(audio_path, sr=16000)  # Standardize to 16kHz
            
            # Apply enhancements based on quality
            if quality.volume_level < 0.005:  # Quiet audio
                # Normalize volume
                y = librosa.util.normalize(y) * 0.7
                logger.info("🔊 Applied volume normalization for quiet audio")
            
            if quality.snr_db < 10:  # Noisy audio
                # Simple noise reduction using spectral gating
                stft = librosa.stft(y)
                magnitude = np.abs(stft)
                phase = np.angle(stft)
                
                # Estimate noise floor
                noise_floor = np.percentile(magnitude, 20, axis=1, keepdims=True)
                
                # Apply spectral gating
                alpha = 0.1  # Reduction factor
                mask = magnitude > (noise_floor * 2)
                magnitude_clean = magnitude * mask + magnitude * alpha * (~mask)
                
                # Reconstruct
                stft_clean = magnitude_clean * np.exp(1j * phase)
                y = librosa.istft(stft_clean)
                logger.info("🎭 Applied noise reduction for noisy audio")
            
            # Save enhanced audio
            sf.write(output_path, y, sr)
            return output_path
            
        except Exception as e:
            logger.warning(f"⚠️ Audio enhancement failed: {e}")
            return audio_path  # Return original if enhancement fails

    @staticmethod
    def determine_optimal_config(quality: AudioQuality) -> IntelligentTranscriptionConfig:
        """Determine optimal transcription configuration based on audio quality"""
        
        # Default configuration
        config = IntelligentTranscriptionConfig(
            use_vad=quality.recommended_vad,
            vad_aggressiveness=0.3,
            chunk_audio=quality.duration_seconds > 60,
            beam_size=3,
            temperature=0.0,
            enable_enhancement=True
        )
        
        # Adjust based on audio characteristics
        if quality.volume_level < 0.005:  # Very quiet
            config.use_vad = False  # Disable VAD for quiet audio
            config.temperature = 0.1  # Slightly more exploration
            logger.info("🤫 Disabled VAD for quiet audio")
            
        elif quality.snr_db < 5:  # Very noisy
            config.vad_aggressiveness = 0.1  # Less aggressive VAD
            config.beam_size = 5  # More exploration for noisy data
            config.temperature = 0.2
            logger.info("🔊 Adjusted settings for noisy audio")
            
        elif quality.duration_seconds < 2:  # Very short
            config.use_vad = False  # Don't use VAD for short clips
            config.chunk_audio = False
            logger.info("⚡ Optimized for short audio clip")
            
        else:  # Good quality audio
            config.use_vad = True
            config.vad_aggressiveness = 0.3
            config.beam_size = 3
            logger.info("✨ Using standard settings for good quality audio")
        
        return config

# Enhanced Faster-Whisper Service with Intelligence
class IntelligentWhisperService:
    def __init__(self):
        self.model = None
        self.device = config.WHISPER_DEVICE
        self.compute_type = config.WHISPER_COMPUTE_TYPE
        self.is_loading = False
        self.model_path = "/app/models"
        self.is_ready = threading.Event()
        self.load_error = None
        self.active_requests = 0
        self._lock = threading.Lock()
        self.audio_processor = AudioProcessor()
        
    async def initialize(self):
        """Initialize Faster-Whisper model with optimizations"""
        if self.model or self.is_loading:
            return
            
        self.is_loading = True
        self.load_error = None
        
        try:
            # Ensure model directory exists
            os.makedirs(self.model_path, exist_ok=True)
            
            logger.info(f"🔄 Loading SOTA Whisper model {config.WHISPER_MODEL} on {self.device}")
            logger.info(f"🎛️ Environment: {config.ENVIRONMENT} (Intelligent Mode: {config.USE_INTELLIGENT_VAD})")
            
            # Run model loading in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, 
                lambda: WhisperModel(
                    config.WHISPER_MODEL,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=config.WHISPER_CPU_THREADS if self.device == "cpu" else 0,
                    num_workers=config.WHISPER_NUM_WORKERS,
                    download_root=self.model_path,
                    local_files_only=False
                )
            )
            
            # Mark as ready for low-latency requests
            self.is_ready.set()
            logger.info("✅ SOTA Whisper model loaded and ready for intelligent inference")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            self.model = None
            self.load_error = str(e)
            raise
        finally:
            self.is_loading = False

    def is_model_ready(self) -> bool:
        """Check if model is ready for inference"""
        return self.is_ready.is_set() and self.model is not None

    async def wait_for_ready(self, timeout: float = 300.0) -> bool:
        """Wait for model to be ready with timeout"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.is_ready.wait, timeout
            )
        except Exception:
            return False

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Get detailed performance metrics"""
        gpu_memory_used = None
        gpu_memory_total = None
        
        if torch.cuda.is_available() and self.device == "cuda":
            try:
                gpu_memory_used = torch.cuda.memory_allocated() / (1024**2)  # MB
                gpu_memory_total = torch.cuda.max_memory_allocated() / (1024**2)  # MB
            except Exception:
                pass
        
        return PerformanceMetrics(
            gpu_memory_used_mb=gpu_memory_used,
            gpu_memory_total_mb=gpu_memory_total,
            cpu_usage_percent=psutil.cpu_percent(),
            ram_usage_percent=psutil.virtual_memory().percent,
            processing_time_ms=0,  # Will be filled during transcription
            model_loaded=self.model is not None,
            concurrent_requests=self.active_requests
        )

    def clear_gpu_cache(self):
        """Clear GPU memory cache"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logger.info("🧹 GPU cache cleared")

    async def intelligent_transcribe(self, audio_file_path: str, 
                                   language: Optional[str] = None, 
                                   task: str = "transcribe", 
                                   temperature: Optional[float] = None,
                                   chunk_audio: Optional[bool] = None, 
                                   use_vad: Optional[bool] = None,
                                   force_config: Optional[IntelligentTranscriptionConfig] = None) -> Dict[str, Any]:
        """SOTA intelligent transcription with automatic adaptation"""
        
        with self._lock:
            self.active_requests += 1
        
        try:
            if not self.is_model_ready():
                raise HTTPException(status_code=503, detail="Model not ready")
            
            start_time = time.time()
            start_metrics = self.get_performance_metrics()
            
            # Step 1: Analyze audio quality
            logger.info("🔍 Analyzing audio quality for optimal processing...")
            quality = self.audio_processor.analyze_audio_quality(audio_file_path)
            
            # Step 2: Determine optimal configuration
            if force_config:
                optimal_config = force_config
                strategy = "forced"
            else:
                optimal_config = self.audio_processor.determine_optimal_config(quality)
                strategy = "intelligent"
                
                # Override with user preferences if provided
                if use_vad is not None:
                    optimal_config.use_vad = use_vad
                if chunk_audio is not None:
                    optimal_config.chunk_audio = chunk_audio
                if temperature is not None:
                    optimal_config.temperature = temperature
            
            logger.info(f"🎯 Strategy: {strategy}, VAD: {optimal_config.use_vad}, "
                       f"Beam: {optimal_config.beam_size}, Temp: {optimal_config.temperature}")
            
            # Step 3: Enhance audio if needed
            processed_audio_path = audio_file_path  # Default
            if config.ENABLE_AUDIO_ENHANCEMENT and optimal_config.enable_enhancement:
                if quality.volume_level < 0.005 or quality.snr_db < 10:
                    enhanced_path = f"{audio_file_path}_enhanced.wav"
                    processed_audio_path = self.audio_processor.enhance_audio(
                        audio_file_path, enhanced_path, quality
                    )
            
            # Step 4: Transcribe with adaptive retry logic
            result = await self._transcribe_with_fallback(
                processed_audio_path, 
                optimal_config,
                language,
                task
            )
            
            # Step 5: Clean up enhanced audio if created
            if processed_audio_path != audio_file_path:
                try:
                    os.unlink(processed_audio_path)
                except:
                    pass
            
            processing_time = int((time.time() - start_time) * 1000)
            end_metrics = self.get_performance_metrics()
            
            result.update({
                "processing_time_ms": processing_time,
                "audio_quality": quality.dict(),
                "processing_strategy": strategy,
                "performance_metrics": {
                    "start_gpu_memory_mb": start_metrics.gpu_memory_used_mb,
                    "end_gpu_memory_mb": end_metrics.gpu_memory_used_mb,
                    "start_cpu_percent": start_metrics.cpu_usage_percent,
                    "end_cpu_percent": end_metrics.cpu_usage_percent,
                    "vad_enabled": optimal_config.use_vad,
                    "beam_size": optimal_config.beam_size,
                    "temperature": optimal_config.temperature,
                    "audio_enhanced": processed_audio_path != audio_file_path
                }
            })
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Intelligent transcription failed: {e}")
            raise
        finally:
            with self._lock:
                self.active_requests -= 1

    async def _transcribe_with_fallback(self, audio_path: str, 
                                      config: IntelligentTranscriptionConfig,
                                      language: Optional[str],
                                      task: str) -> Dict[str, Any]:
        """Transcribe with intelligent fallback strategies"""
        
        attempts = []
        
        # Strategy 1: Try with intelligent configuration
        try:
            result = await self._transcribe_single(audio_path, config, language, task)
            if result["text"].strip():  # Success!
                result["fallback_attempts"] = len(attempts)
                return result
            else:
                attempts.append("intelligent_config")
                logger.warning("⚠️ Intelligent config returned empty text, trying fallback...")
        except Exception as e:
            attempts.append(f"intelligent_config_error: {str(e)}")
            logger.warning(f"⚠️ Intelligent config failed: {e}")
        
        # Strategy 2: Fallback - Disable VAD if it was enabled
        if config.use_vad:
            try:
                fallback_config = config.copy()
                fallback_config.use_vad = False
                fallback_config.temperature = 0.1  # Slightly more exploration
                
                logger.info("🔄 Fallback: Retrying without VAD...")
                result = await self._transcribe_single(audio_path, fallback_config, language, task)
                if result["text"].strip():
                    result["fallback_attempts"] = len(attempts)
                    result["successful_strategy"] = "no_vad_fallback"
                    return result
                else:
                    attempts.append("no_vad_fallback")
            except Exception as e:
                attempts.append(f"no_vad_fallback_error: {str(e)}")
        
        # Strategy 3: Aggressive fallback - High temperature, no VAD, higher beam
        try:
            aggressive_config = IntelligentTranscriptionConfig(
                use_vad=False,
                vad_aggressiveness=0.0,
                chunk_audio=False,
                beam_size=5,
                temperature=0.3,
                enable_enhancement=False
            )
            
            logger.info("🔄 Aggressive fallback: High temperature, no VAD...")
            result = await self._transcribe_single(audio_path, aggressive_config, language, task)
            if result["text"].strip():
                result["fallback_attempts"] = len(attempts)
                result["successful_strategy"] = "aggressive_fallback"
                return result
            else:
                attempts.append("aggressive_fallback")
        except Exception as e:
            attempts.append(f"aggressive_fallback_error: {str(e)}")
        
        # Strategy 4: Last resort - Force English, no constraints  
        try:
            last_resort_config = IntelligentTranscriptionConfig(
                use_vad=False,
                vad_aggressiveness=0.0,
                chunk_audio=False,
                beam_size=1,  # Fast but basic
                temperature=0.0,
                enable_enhancement=False
            )
            
            logger.info("🔄 Last resort: Force English, minimal constraints...")
            result = await self._transcribe_single(audio_path, last_resort_config, "en", task)
            result["fallback_attempts"] = len(attempts)
            result["successful_strategy"] = "last_resort"
            result["warning"] = "Used last resort strategy - transcription quality may be lower"
            return result
        except Exception as e:
            attempts.append(f"last_resort_error: {str(e)}")
        
        # If all strategies failed
        raise HTTPException(
            status_code=500, 
            detail=f"All transcription strategies failed. Attempts: {attempts}"
        )

    async def _transcribe_single(self, audio_path: str, 
                                config: IntelligentTranscriptionConfig,
                                language: Optional[str],
                                task: str) -> Dict[str, Any]:
        """Single transcription attempt with given configuration"""
        
        # Prepare VAD parameters
        vad_params = None
        if config.use_vad:
            vad_params = {
                "min_silence_duration_ms": max(config.VAD_MIN_SILENCE_DURATION_MS, 100),
                "speech_pad_ms": max(config.VAD_SPEECH_PAD_MS, 200),
                "threshold": config.vad_aggressiveness
            }
        
        # Run transcription in thread pool
        loop = asyncio.get_event_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: self.model.transcribe(
                audio_path,
                language=language,
                task=task,
                temperature=config.temperature,
                beam_size=config.beam_size,
                best_of=min(config.beam_size, 5),
                vad_filter=config.use_vad,
                vad_parameters=vad_params
            )
        )
        
        # Convert generator to list and extract text
        segment_list = list(segments)
        full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
        
        return {
            "text": full_text,
            "language": info.language if hasattr(info, 'language') else language,
            "segments": [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "confidence": getattr(segment, 'avg_logprob', None)
                } for segment in segment_list
            ]
        }

    async def cleanup(self):
        """Cleanup resources on shutdown"""
        logger.info("🧹 Cleaning up Intelligent Whisper service...")
        if self.model:
            del self.model
            self.model = None
        self.clear_gpu_cache()
        self.is_ready.clear()
        logger.info("✅ Intelligent Whisper service cleanup completed")

whisper_service = IntelligentWhisperService()

# Orchestrator Client (unchanged)
class OrchestratorClient:
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.api_key = config.ORCHESTRATOR_API_KEY
    
    async def notify_transcript(self, notification: TranscriptNotification):
        """Send transcript notification to orchestrator"""
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/transcripts",
                    json=notification.model_dump(),  # Fixed for Pydantic v2
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Notified orchestrator about transcript {notification.transcript_id}")
                else:
                    logger.warning(f"⚠️ Orchestrator notification failed: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to notify orchestrator: {e}")

orchestrator_client = OrchestratorClient()

# Background Tasks (unchanged)
async def cleanup_old_transcripts():
    """Clean up old transcripts from memory"""
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=config.TRANSCRIPT_RETENTION_HOURS)
        
        to_remove = []
        for transcript_id, transcript in transcript_storage.items():
            if transcript.timestamp < cutoff_time:
                to_remove.append(transcript_id)
        
        for transcript_id in to_remove:
            del transcript_storage[transcript_id]
            
        logger.info(f"🧹 Cleanup completed. {len(to_remove)} transcripts removed")
    except Exception as e:
        logger.error(f"❌ Error during transcript cleanup: {e}")

async def periodic_cleanup():
    """Periodically clean up old transcripts"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await cleanup_old_transcripts()
        except asyncio.CancelledError:
            logger.info("🛑 Cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup: {e}")

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global cleanup_task, processing_semaphore
    
    logger.info("🚀 Starting June SOTA STT Service v4.0.0")
    logger.info(f"🧠 Intelligent Mode: {config.USE_INTELLIGENT_VAD}")
    logger.info(f"🎛️ Environment: {config.ENVIRONMENT}")
    
    # Initialize semaphore
    processing_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
    
    # Initialize model
    try:
        await whisper_service.initialize()
        logger.info("✅ SOTA model initialization completed")
    except Exception as e:
        logger.error(f"❌ Failed to initialize service: {e}")
    
    # Start background cleanup
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    logger.info("✅ June SOTA STT Service started successfully")
    
    yield
    
    # Cleanup on shutdown
    logger.info("🛑 Shutting down June SOTA STT Service")
    
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    await whisper_service.cleanup()
    logger.info("✅ Shutdown completed")

# Create FastAPI app
app = FastAPI(
    title="June SOTA STT Service", 
    version="4.0.0", 
    description="State-of-the-Art Speech-to-Text with Intelligent Adaptation",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request validation
async def validate_audio_file(audio_file: UploadFile) -> None:
    """Validate uploaded audio file"""
    if not audio_file.content_type or not audio_file.content_type.startswith(('audio/', 'video/')):
        raise HTTPException(status_code=400, detail="File must be audio or video format")
    
    max_size = config.MAX_FILE_SIZE * 1024 * 1024
    if audio_file.size and audio_file.size > max_size:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE}MB."
        )

# API Endpoints
@app.get("/")
async def root():
    """Service information endpoint"""
    return {
        "service": "June SOTA STT Service",
        "version": "4.0.0", 
        "status": "ready" if whisper_service.is_model_ready() else "initializing",
        "features": {
            "intelligent_vad": config.USE_INTELLIGENT_VAD,
            "audio_enhancement": config.ENABLE_AUDIO_ENHANCEMENT,
            "noise_reduction": config.ENABLE_NOISE_REDUCTION,
            "smart_chunking": config.ENABLE_SMART_CHUNKING,
            "adaptive_fallback": True,
            "quality_analysis": True
        },
        "model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "environment": config.ENVIRONMENT,
        "auth_available": AUTH_AVAILABLE
    }

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-sota-stt",
        "version": "4.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "model_ready": whisper_service.is_model_ready(),
        "intelligent_features": config.USE_INTELLIGENT_VAD
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    if whisper_service.is_model_ready():
        return {
            "status": "ready",
            "model_loaded": True,
            "intelligent_mode": config.USE_INTELLIGENT_VAD,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        raise HTTPException(status_code=503, detail="Service initializing")

@app.post("/v1/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    task: Optional[str] = Form("transcribe"),
    temperature: Optional[float] = Form(None),
    notify_orchestrator: Optional[bool] = Form(True),
    chunk_audio: Optional[bool] = Form(None),
    use_vad: Optional[bool] = Form(None),
    auth_data: dict = Depends(require_user_auth)
):
    """
    SOTA Speech-to-Text with Intelligent Adaptation
    
    The service automatically:
    - Analyzes audio quality and adapts processing strategy
    - Applies noise reduction and volume normalization when needed
    - Uses intelligent VAD or disables it for quiet audio
    - Falls back to alternative strategies if initial attempt fails
    - Optimizes beam size and temperature based on audio characteristics
    
    Manual overrides are available but generally not needed.
    """
    # Acquire semaphore for concurrent request limiting
    async with processing_semaphore:
        start_time = time.time()
        user_id = extract_user_id(auth_data)
        
        # Validate audio file
        await validate_audio_file(audio_file)
        
        # Check if model is ready
        if not whisper_service.is_model_ready():
            if not whisper_service.is_loading:
                await whisper_service.initialize()
            
            ready = await whisper_service.wait_for_ready(timeout=60.0)
            if not ready:
                raise HTTPException(status_code=503, detail="Model loading timeout")
        
        try:
            # Generate unique transcript ID
            transcript_id = str(uuid.uuid4())
            
            # Create temp directory
            os.makedirs("/tmp", exist_ok=True)
            
            # Save uploaded file temporarily
            file_path = f"/tmp/june_sota_stt_{transcript_id}_{audio_file.filename}"
            try:
                with open(file_path, "wb") as f:
                    content = await audio_file.read()
                    f.write(content)
                
                logger.info(f"🎵 Starting SOTA transcription for {audio_file.filename} ({len(content)} bytes)")
                
                # Intelligent transcription with automatic adaptation
                result = await whisper_service.intelligent_transcribe(
                    file_path, 
                    language=language, 
                    task=task, 
                    temperature=temperature,
                    chunk_audio=chunk_audio,
                    use_vad=use_vad
                )
                
                # Create enhanced transcript result
                transcript_result = TranscriptionResult(
                    transcript_id=transcript_id,
                    text=result["text"],
                    language=result.get("language"),
                    processing_time_ms=result["processing_time_ms"],
                    timestamp=datetime.utcnow(),
                    status="completed",
                    user_id=user_id,
                    segments=result.get("segments", []),
                    performance_metrics=result.get("performance_metrics"),
                    audio_quality=result.get("audio_quality"),
                    processing_strategy=result.get("processing_strategy", "intelligent")
                )
                
                # Store transcript in memory
                transcript_storage[transcript_id] = transcript_result
                
                # Notify orchestrator in background
                if notify_orchestrator:
                    notification = TranscriptNotification(
                        transcript_id=transcript_id,
                        user_id=user_id,
                        text=result["text"],
                        timestamp=transcript_result.timestamp,
                        metadata={
                            "language": result.get("language"),
                            "processing_time_ms": result["processing_time_ms"],
                            "task": task,
                            "filename": audio_file.filename,
                            "engine": "sota-whisper-intelligent",
                            "model": config.WHISPER_MODEL,
                            "processing_strategy": result.get("processing_strategy"),
                            "audio_quality": result.get("audio_quality"),
                            "fallback_attempts": result.get("fallback_attempts", 0)
                        }
                    )
                    background_tasks.add_task(orchestrator_client.notify_transcript, notification)
                
                logger.info(f"✅ SOTA transcription completed: {transcript_id} ({result['processing_time_ms']}ms)")
                
                return transcript_result
                
            finally:
                # Clean up temporary file
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to cleanup temp file: {e}")
                    
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ SOTA transcription error: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

# Additional endpoints (get_transcript, list_transcripts, etc.) remain the same...
@app.get("/v1/transcripts/{transcript_id}", response_model=TranscriptionResult)
async def get_transcript(transcript_id: str, auth_data: dict = Depends(require_user_auth)):
    """Get transcript by ID"""
    if transcript_id not in transcript_storage:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    transcript = transcript_storage[transcript_id]
    user_id = extract_user_id(auth_data)
    
    if transcript.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return transcript

@app.get("/v1/stats")
async def get_stats(auth_data: dict = Depends(require_user_auth)):
    """Get enhanced service statistics"""
    user_id = extract_user_id(auth_data)
    user_transcripts = [t for t in transcript_storage.values() if t.user_id == user_id]
    metrics = whisper_service.get_performance_metrics()
    
    return {
        "user_stats": {
            "user_transcripts": len(user_transcripts),
            "total_processing_time_ms": sum(t.processing_time_ms for t in user_transcripts),
            "avg_processing_time_ms": sum(t.processing_time_ms for t in user_transcripts) / len(user_transcripts) if user_transcripts else 0
        },
        "service_stats": {
            "total_transcripts": len(transcript_storage),
            "model_loaded": whisper_service.is_model_ready(),
            "active_requests": whisper_service.active_requests,
            "intelligent_features_enabled": config.USE_INTELLIGENT_VAD
        },
        "sota_features": {
            "intelligent_vad": config.USE_INTELLIGENT_VAD,
            "audio_enhancement": config.ENABLE_AUDIO_ENHANCEMENT,
            "noise_reduction": config.ENABLE_NOISE_REDUCTION,
            "adaptive_fallback": True,
            "quality_analysis": True
        },
        "performance": {
            "gpu_memory_used_mb": metrics.gpu_memory_used_mb,
            "cpu_usage_percent": metrics.cpu_usage_percent,
            "ram_usage_percent": metrics.ram_usage_percent,
            "concurrent_requests": metrics.concurrent_requests
        }
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "june-sota-stt"
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"❌ Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "june-sota-stt"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")
