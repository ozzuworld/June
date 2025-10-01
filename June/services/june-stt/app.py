# June/services/june-stt/app.py
# Enhanced STT microservice with Keycloak authentication and Faster-Whisper optimization

import os
import time
import uuid
import asyncio
import logging
import threading
import psutil
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import torch
from faster_whisper import WhisperModel
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks, Header
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

# Enhanced Configuration
class Config:
    # Environment
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # production, accuracy, development
    
    # Orchestrator
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")
    ORCHESTRATOR_API_KEY = os.getenv("ORCHESTRATOR_API_KEY", "")
    
    # Faster-Whisper Configuration
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16" if torch.cuda.is_available() else "int8")
    
    # Performance Settings (environment-specific)
    if ENVIRONMENT == "production":
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "1"))  # Faster inference
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "1"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
    elif ENVIRONMENT == "accuracy":
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))  # Better accuracy
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "5"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "4"))
    else:  # development
        WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
        WHISPER_BEST_OF = int(os.getenv("WHISPER_BEST_OF", "3"))
        WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "8"))
    
    WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    
    # Resource Limits
    MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))
    MAX_AUDIO_LENGTH = int(os.getenv("MAX_AUDIO_LENGTH", "600"))  # 10 minutes
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "25"))  # 25MB
    
    # Audio Processing
    CHUNK_LENGTH = int(os.getenv("CHUNK_LENGTH", "30"))  # seconds
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "1"))   # seconds
    
    # Storage
    TRANSCRIPT_RETENTION_HOURS = int(os.getenv("TRANSCRIPT_RETENTION_HOURS", "24"))
    
    # Service
    PORT = int(os.getenv("PORT", "8000"))

config = Config()

# Models
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

class TranscriptionRequest(BaseModel):
    language: Optional[str] = None
    task: Optional[str] = "transcribe"  # transcribe or translate
    temperature: Optional[float] = 0.0
    notify_orchestrator: Optional[bool] = True
    chunk_audio: Optional[bool] = True
    use_vad: Optional[bool] = True

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

# Enhanced Faster-Whisper Service
class WhisperService:
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
        
    async def initialize(self):
        """Initialize Faster-Whisper model with optimizations"""
        if self.model or self.is_loading:
            return
            
        self.is_loading = True
        self.load_error = None
        
        try:
            # Ensure model directory exists
            os.makedirs(self.model_path, exist_ok=True)
            
            logger.info(f"🔄 Loading Faster-Whisper model {config.WHISPER_MODEL} on {self.device} ({self.compute_type})")
            logger.info(f"📁 Model cache directory: {self.model_path}")
            logger.info(f"🎛️ Environment: {config.ENVIRONMENT}")
            
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
            logger.info("✅ Faster-Whisper model loaded and ready for inference")
            logger.info(f"🚀 Model cached at: {self.model_path}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Faster-Whisper model: {e}")
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

    def get_status(self) -> Dict[str, Any]:
        """Get detailed model status"""
        if self.model and self.is_ready.is_set():
            status = "ready"
        elif self.is_loading:
            status = "loading"
        elif self.load_error:
            status = "error"
        else:
            status = "not_loaded"
        
        metrics = self.get_performance_metrics()
            
        return {
            "status": status,
            "ready": self.is_model_ready(),
            "loading": self.is_loading,
            "error": self.load_error,
            "device": self.device,
            "compute_type": self.compute_type,
            "model_path": self.model_path,
            "active_requests": self.active_requests,
            "environment": config.ENVIRONMENT,
            "performance": {
                "gpu_memory_used_mb": metrics.gpu_memory_used_mb,
                "cpu_usage_percent": metrics.cpu_usage_percent,
                "ram_usage_percent": metrics.ram_usage_percent
            }
        }

    def _preprocess_audio(self, audio_path: str) -> str:
        """Preprocess audio for optimal performance"""
        # For now, return original path
        # Future: Add VAD, normalization, format conversion
        return audio_path

    def _chunk_audio(self, audio_path: str, chunk_length: int = None, overlap: int = None) -> List[str]:
        """Chunk long audio files for better processing"""
        chunk_length = chunk_length or config.CHUNK_LENGTH
        overlap = overlap or config.CHUNK_OVERLAP
        
        # For now, return single chunk
        # Future: Implement smart chunking with VAD
        return [audio_path]

    async def transcribe_with_fallback(self, audio_file_path: str, language: Optional[str] = None, 
                                     task: str = "transcribe", temperature: float = 0.0,
                                     chunk_audio: bool = True, use_vad: bool = True) -> Dict[str, Any]:
        """Transcribe with error handling and fallback"""
        with self._lock:
            self.active_requests += 1
        
        try:
            return await self._transcribe_internal(
                audio_file_path, language, task, temperature, chunk_audio, use_vad
            )
        except torch.cuda.OutOfMemoryError:
            logger.warning("⚠️ GPU OOM detected, clearing cache and retrying...")
            self.clear_gpu_cache()
            # Retry once
            return await self._transcribe_internal(
                audio_file_path, language, task, temperature, False, use_vad  # Disable chunking on retry
            )
        except Exception as e:
            logger.error(f"❌ Transcription failed: {e}")
            raise
        finally:
            with self._lock:
                self.active_requests -= 1
    
    async def _transcribe_internal(self, audio_file_path: str, language: Optional[str] = None, 
                                  task: str = "transcribe", temperature: float = 0.0,
                                  chunk_audio: bool = True, use_vad: bool = True) -> Dict[str, Any]:
        """Internal transcription method"""
        if not self.is_model_ready():
            if self.is_loading:
                raise HTTPException(
                    status_code=503, 
                    detail="Faster-Whisper model is still loading, please try again in a few moments"
                )
            elif self.load_error:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Faster-Whisper model failed to load: {self.load_error}"
                )
            else:
                raise HTTPException(
                    status_code=500, 
                    detail="Faster-Whisper model not initialized"
                )
        
        start_time = time.time()
        start_metrics = self.get_performance_metrics()
        
        try:
            # Preprocess audio
            processed_audio = self._preprocess_audio(audio_file_path)
            
            # Chunk if needed and requested
            if chunk_audio:
                chunks = self._chunk_audio(processed_audio)
            else:
                chunks = [processed_audio]
            
            all_segments = []
            full_text = ""
            
            # Process each chunk
            for chunk_path in chunks:
                # Run transcription in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                segments, info = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(
                        chunk_path,
                        language=language,
                        task=task,
                        temperature=temperature,
                        beam_size=config.WHISPER_BEAM_SIZE,
                        best_of=config.WHISPER_BEST_OF,
                        vad_filter=use_vad,
                        vad_parameters=dict(
                            min_silence_duration_ms=500,
                            speech_pad_ms=200
                        ) if use_vad else None
                    )
                )
                
                # Convert generator to list (important for faster-whisper!)
                chunk_segments = list(segments)
                all_segments.extend(chunk_segments)
                full_text += " ".join([segment.text for segment in chunk_segments]).strip() + " "
            
            processing_time = int((time.time() - start_time) * 1000)
            end_metrics = self.get_performance_metrics()
            
            return {
                "text": full_text.strip(),
                "language": info.language if 'info' in locals() else language,
                "segments": [
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text.strip(),
                        "confidence": getattr(segment, 'avg_logprob', None)
                    } for segment in all_segments
                ],
                "processing_time_ms": processing_time,
                "performance_metrics": {
                    "start_gpu_memory_mb": start_metrics.gpu_memory_used_mb,
                    "end_gpu_memory_mb": end_metrics.gpu_memory_used_mb,
                    "start_cpu_percent": start_metrics.cpu_usage_percent,
                    "end_cpu_percent": end_metrics.cpu_usage_percent,
                    "chunks_processed": len(chunks),
                    "vad_enabled": use_vad,
                    "beam_size": config.WHISPER_BEAM_SIZE
                }
            }
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"❌ Transcription failed after {processing_time}ms: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    async def cleanup(self):
        """Cleanup resources on shutdown"""
        logger.info("🧹 Cleaning up Whisper service resources...")
        if self.model:
            del self.model
            self.model = None
        self.clear_gpu_cache()
        self.is_ready.clear()
        logger.info("✅ Whisper service cleanup completed")

whisper_service = WhisperService()

# Orchestrator Client
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
                    json=notification.dict(),
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Notified orchestrator about transcript {notification.transcript_id}")
                else:
                    logger.warning(f"⚠️ Orchestrator notification failed: {response.status_code} - {response.text}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to notify orchestrator: {e}")

orchestrator_client = OrchestratorClient()

# Background Tasks
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
            logger.info(f"🗑️ Cleaned up old transcript: {transcript_id}")
            
        logger.info(f"🧹 Cleanup completed. {len(to_remove)} transcripts removed, {len(transcript_storage)} remaining")
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

# Lifespan context manager for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global cleanup_task, processing_semaphore
    
    logger.info("🚀 Starting June STT Service v3.0.0 (Enhanced Faster-Whisper)")
    logger.info(f"🔧 Config: Model={config.WHISPER_MODEL}, Device={config.WHISPER_DEVICE}, Compute={config.WHISPER_COMPUTE_TYPE}")
    logger.info(f"🎛️ Environment: {config.ENVIRONMENT}")
    logger.info(f"⚡ Performance: Beam={config.WHISPER_BEAM_SIZE}, Batch={config.WHISPER_BATCH_SIZE}")
    
    # Initialize semaphore for concurrent request limiting
    processing_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
    
    # Initialize Faster-Whisper model at startup
    logger.info("🔄 Initializing enhanced Faster-Whisper model at startup...")
    try:
        await whisper_service.initialize()
        logger.info("✅ Model initialization completed successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Faster-Whisper service: {e}")
        logger.warning("⚠️ Service will continue but model loading will be attempted on first request")
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    logger.info("✅ June STT Service started successfully")
    
    yield
    
    # Cleanup on shutdown
    logger.info("🛑 Shutting down June STT Service")
    
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    # Cleanup Whisper service
    await whisper_service.cleanup()
    
    logger.info("✅ Shutdown completed")

# Create FastAPI app with lifespan
app = FastAPI(
    title="June STT Service (Enhanced Faster-Whisper)", 
    version="3.0.0", 
    description="High-performance Speech-to-Text microservice with enhanced optimizations and Keycloak authentication",
    lifespan=lifespan
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with your frontend domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request validation
async def validate_audio_file(audio_file: UploadFile) -> None:
    """Validate uploaded audio file"""
    # Check file type
    if not audio_file.content_type or not audio_file.content_type.startswith(('audio/', 'video/')):
        raise HTTPException(status_code=400, detail="File must be audio or video format")
    
    # Check file size
    max_size = config.MAX_FILE_SIZE * 1024 * 1024  # Convert MB to bytes
    if audio_file.size and audio_file.size > max_size:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE}MB."
        )

# API Endpoints
@app.get("/")
async def root():
    """Service information endpoint"""
    model_status_info = whisper_service.get_status()
    
    return {
        "service": "June STT Service (Enhanced Faster-Whisper)",
        "version": "3.0.0", 
        "status": "healthy" if model_status_info["ready"] else "initializing",
        "whisper_model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "compute_type": config.WHISPER_COMPUTE_TYPE,
        "environment": config.ENVIRONMENT,
        "model_status": model_status_info["status"],
        "model_ready": model_status_info["ready"],
        "auth_available": AUTH_AVAILABLE,
        "performance": model_status_info.get("performance", {}),
        "limits": {
            "max_concurrent_requests": config.MAX_CONCURRENT_REQUESTS,
            "max_audio_length": config.MAX_AUDIO_LENGTH,
            "max_file_size_mb": config.MAX_FILE_SIZE
        },
        "endpoints": {
            "transcribe": "/v1/transcribe",
            "transcripts": "/v1/transcripts/{transcript_id}",
            "health": "/healthz",
            "ready": "/ready",
            "metrics": "/v1/metrics"
        }
    }

@app.get("/healthz")
async def health_check():
    """Kubernetes liveness probe - always healthy if service is running"""
    model_status_info = whisper_service.get_status()
    
    return {
        "status": "healthy",
        "service": "june-stt",
        "version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "whisper_model_status": model_status_info["status"],
        "model_ready": model_status_info["ready"],
        "auth_status": "keycloak" if AUTH_AVAILABLE else "fallback",
        "transcripts_in_memory": len(transcript_storage),
        "device": config.WHISPER_DEVICE,
        "compute_type": config.WHISPER_COMPUTE_TYPE,
        "environment": config.ENVIRONMENT,
        "active_requests": model_status_info.get("active_requests", 0)
    }

@app.get("/ready")
async def readiness_check():
    """Kubernetes readiness probe - only ready when model is loaded"""
    model_status_info = whisper_service.get_status()
    
    if model_status_info["ready"]:
        return {
            "status": "ready",
            "model_loaded": True,
            "service": "june-stt",
            "timestamp": datetime.utcnow().isoformat(),
            "performance": model_status_info.get("performance", {})
        }
    else:
        raise HTTPException(
            status_code=503, 
            detail={
                "status": "not_ready",
                "model_status": model_status_info["status"],
                "message": f"Service initializing - model status: {model_status_info['status']}",
                "error": model_status_info.get("error")
            }
        )

@app.get("/v1/metrics")
async def get_metrics(auth_data: dict = Depends(require_service_auth)):
    """Get detailed service metrics"""
    model_status = whisper_service.get_status()
    metrics = whisper_service.get_performance_metrics()
    
    return {
        "service_metrics": {
            "model_ready": model_status["ready"],
            "active_requests": model_status["active_requests"],
            "transcripts_in_memory": len(transcript_storage),
            "environment": config.ENVIRONMENT
        },
        "performance_metrics": {
            "gpu_memory_used_mb": metrics.gpu_memory_used_mb,
            "gpu_memory_total_mb": metrics.gpu_memory_total_mb,
            "cpu_usage_percent": metrics.cpu_usage_percent,
            "ram_usage_percent": metrics.ram_usage_percent,
            "model_loaded": metrics.model_loaded,
            "concurrent_requests": metrics.concurrent_requests
        },
        "configuration": {
            "whisper_model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "beam_size": config.WHISPER_BEAM_SIZE,
            "batch_size": config.WHISPER_BATCH_SIZE,
            "max_concurrent": config.MAX_CONCURRENT_REQUESTS,
            "max_file_size_mb": config.MAX_FILE_SIZE
        }
    }

@app.post("/v1/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = None,
    task: Optional[str] = "transcribe",
    temperature: Optional[float] = 0.0,
    notify_orchestrator: Optional[bool] = True,
    chunk_audio: Optional[bool] = True,
    use_vad: Optional[bool] = True,
    auth_data: dict = Depends(require_user_auth)
):
    """
    Enhanced transcription with optimizations and performance monitoring
    
    - **audio_file**: Audio file (wav, mp3, m4a, etc.)
    - **language**: Source language (optional, auto-detected if not provided)  
    - **task**: 'transcribe' or 'translate' (to English)
    - **temperature**: Sampling temperature (0.0 = deterministic)
    - **notify_orchestrator**: Whether to notify orchestrator service
    - **chunk_audio**: Enable audio chunking for long files
    - **use_vad**: Enable Voice Activity Detection for better performance
    """
    # Acquire semaphore for concurrent request limiting
    async with processing_semaphore:
        start_time = time.time()
        user_id = extract_user_id(auth_data)
        
        # Validate audio file
        await validate_audio_file(audio_file)
        
        # Check if model is ready, if not try to initialize
        if not whisper_service.is_model_ready():
            if not whisper_service.is_loading:
                logger.info("🔄 Loading Faster-Whisper model on demand...")
                await whisper_service.initialize()
            
            # Wait for model to be ready (with timeout)
            logger.info("⏳ Waiting for model to be ready...")
            ready = await whisper_service.wait_for_ready(timeout=60.0)
            if not ready:
                raise HTTPException(
                    status_code=503, 
                    detail="Model is taking too long to load. Please try again in a few minutes."
                )
        
        try:
            # Generate unique transcript ID
            transcript_id = str(uuid.uuid4())
            
            # Create temp directory if it doesn't exist
            os.makedirs("/tmp", exist_ok=True)
            
            # Save uploaded file temporarily
            file_path = f"/tmp/june_stt_{transcript_id}_{audio_file.filename}"
            try:
                with open(file_path, "wb") as f:
                    content = await audio_file.read()
                    f.write(content)
                
                logger.info(f"🎵 Starting enhanced transcription for {audio_file.filename} ({len(content)} bytes)")
                
                # Transcribe audio with enhanced Faster-Whisper
                result = await whisper_service.transcribe_with_fallback(
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
                    performance_metrics=result.get("performance_metrics", {})
                )
                
                # Store transcript in memory
                transcript_storage[transcript_id] = transcript_result
                
                # Notify orchestrator in background if requested
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
                            "engine": "faster-whisper-enhanced",
                            "model": config.WHISPER_MODEL,
                            "device": config.WHISPER_DEVICE,
                            "environment": config.ENVIRONMENT,
                            "performance": result.get("performance_metrics", {}),
                            "segments_count": len(result.get("segments", []))
                        }
                    )
                    background_tasks.add_task(orchestrator_client.notify_transcript, notification)
                
                logger.info(f"✅ Enhanced transcription completed: {transcript_id} for user {user_id} ({result['processing_time_ms']}ms)")
                
                return transcript_result
                
            finally:
                # Clean up temporary file
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to cleanup temp file {file_path}: {e}")
                    
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

@app.get("/v1/transcripts/{transcript_id}", response_model=TranscriptionResult)
async def get_transcript(
    transcript_id: str,
    auth_data: dict = Depends(require_user_auth)
):
    """Get transcript by ID with performance data"""
    if transcript_id not in transcript_storage:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    transcript = transcript_storage[transcript_id]
    user_id = extract_user_id(auth_data)
    
    # Check if user owns this transcript
    if transcript.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return transcript

@app.get("/v1/transcripts")
async def list_transcripts(
    limit: int = 50,
    include_performance: bool = False,
    auth_data: dict = Depends(require_user_auth)
):
    """List recent transcripts for user with optional performance data"""
    user_id = extract_user_id(auth_data)
    
    # Filter transcripts by user
    user_transcripts = [
        transcript for transcript in transcript_storage.values()
        if transcript.user_id == user_id
    ]
    
    user_transcripts.sort(key=lambda x: x.timestamp, reverse=True)
    
    result_transcripts = user_transcripts[:limit]
    
    # Optionally exclude performance metrics for lighter response
    if not include_performance:
        for transcript in result_transcripts:
            transcript.performance_metrics = None
    
    return {
        "transcripts": result_transcripts,
        "total": len(user_transcripts),
        "showing": len(result_transcripts),
        "performance_included": include_performance
    }

@app.delete("/v1/transcripts/{transcript_id}")
async def delete_transcript(
    transcript_id: str,
    auth_data: dict = Depends(require_user_auth)
):
    """Delete transcript by ID"""
    if transcript_id not in transcript_storage:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    transcript = transcript_storage[transcript_id]
    user_id = extract_user_id(auth_data)
    
    # Check if user owns this transcript
    if transcript.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    del transcript_storage[transcript_id]
    return {"message": "Transcript deleted successfully"}

@app.get("/v1/stats")
async def get_stats(auth_data: dict = Depends(require_user_auth)):
    """Get enhanced service statistics"""
    user_id = extract_user_id(auth_data)
    user_transcripts = [t for t in transcript_storage.values() if t.user_id == user_id]
    model_status_info = whisper_service.get_status()
    metrics = whisper_service.get_performance_metrics()
    
    return {
        "user_stats": {
            "user_transcripts": len(user_transcripts),
            "total_processing_time_ms": sum(t.processing_time_ms for t in user_transcripts),
            "avg_processing_time_ms": sum(t.processing_time_ms for t in user_transcripts) / len(user_transcripts) if user_transcripts else 0
        },
        "service_stats": {
            "total_transcripts": len(transcript_storage),
            "model_loaded": model_status_info["ready"],
            "model_loading": model_status_info["loading"],
            "model_status": model_status_info["status"],
            "active_requests": model_status_info["active_requests"]
        },
        "configuration": {
            "whisper_model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "environment": config.ENVIRONMENT,
            "beam_size": config.WHISPER_BEAM_SIZE,
            "batch_size": config.WHISPER_BATCH_SIZE,
            "auth_provider": "keycloak" if AUTH_AVAILABLE else "fallback",
            "engine": "faster-whisper-enhanced"
        },
        "performance": {
            "gpu_memory_used_mb": metrics.gpu_memory_used_mb,
            "cpu_usage_percent": metrics.cpu_usage_percent,
            "ram_usage_percent": metrics.ram_usage_percent,
            "concurrent_requests": metrics.concurrent_requests
        }
    }

# Enhanced error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions properly"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "june-stt"
        },
        headers=exc.headers
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle unexpected exceptions"""
    logger.error(f"❌ Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "june-stt"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")
