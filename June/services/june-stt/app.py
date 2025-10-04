# June/services/june-stt/app.py
# Simple, Correct Faster-Whisper Implementation with Fixed Orchestrator Integration

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
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks, Header, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

# Import shared auth
try:
    from shared import require_user_auth, require_service_auth, extract_user_id, extract_client_id
    AUTH_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Keycloak authentication available")
except ImportError:
    AUTH_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Keycloak authentication not available - using fallback")
    
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

# FIXED: Import the new orchestrator client
from orchestrator_client import get_orchestrator_client

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables
whisper_model = None
transcript_storage = {}
processing_queue = asyncio.Queue()
cleanup_task = None
processing_semaphore = None

# Configuration
class Config:
    # Environment
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
    
    # Faster-Whisper Configuration (Official Documentation)
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16" if torch.cuda.is_available() else "int8")
    
    # Performance Settings (Based on docs)
    WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    
    # Resource Limits
    MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))
    MAX_AUDIO_LENGTH = int(os.getenv("MAX_AUDIO_LENGTH", "600"))  # 10 minutes
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "25"))  # 25MB
    
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

# Simple Faster-Whisper Service (Following Official Docs)
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
        """Initialize Faster-Whisper model (following official docs)"""
        if self.model or self.is_loading:
            return
            
        self.is_loading = True
        self.load_error = None
        
        try:
            os.makedirs(self.model_path, exist_ok=True)
            
            logger.info(f"🔄 Loading Faster-Whisper model {config.WHISPER_MODEL} on {self.device} ({self.compute_type})")
            
            # Load model following official documentation
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
            
            self.is_ready.set()
            logger.info("✅ Faster-Whisper model loaded successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Faster-Whisper model: {e}")
            self.model = None
            self.load_error = str(e)
            raise
        finally:
            self.is_loading = False

    def is_model_ready(self) -> bool:
        return self.is_ready.is_set() and self.model is not None

    async def wait_for_ready(self, timeout: float = 300.0) -> bool:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.is_ready.wait, timeout)
        except Exception:
            return False

    def clear_gpu_cache(self):
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logger.info("🧹 GPU cache cleared")

    async def transcribe(self, audio_file_path: str, 
                        language: Optional[str] = None, 
                        task: str = "transcribe", 
                        temperature: float = 0.0,
                        beam_size: Optional[int] = None,
                        use_vad: bool = False) -> Dict[str, Any]:
        """
        Simple transcription following faster-whisper documentation
        """
        
        with self._lock:
            self.active_requests += 1
        
        try:
            if not self.is_model_ready():
                raise HTTPException(status_code=503, detail="Faster-Whisper model not ready")
            
            start_time = time.time()
            
            # Use beam size from parameter or config
            actual_beam_size = beam_size if beam_size is not None else config.WHISPER_BEAM_SIZE
            
            # Prepare VAD parameters (conservative settings from docs)
            vad_parameters = None
            if use_vad:
                vad_parameters = {
                    "threshold": 0.5,
                    "min_silence_duration_ms": 2000,
                    "speech_pad_ms": 400,
                    "window_size_samples": 1024
                }
            
            logger.info(f"🎯 Transcribing with beam_size={actual_beam_size}, vad={use_vad}, language={language}")
            
            # Run transcription in thread pool following official docs
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None,
                lambda: self.model.transcribe(
                    audio_file_path,
                    beam_size=actual_beam_size,
                    language=language,
                    task=task,
                    temperature=temperature,
                    vad_filter=use_vad,
                    vad_parameters=vad_parameters
                )
            )
            
            # IMPORTANT: Convert generator to list (from docs)
            segment_list = list(segments)
            full_text = " ".join([segment.text.strip() for segment in segment_list]).strip()
            
            processing_time = int((time.time() - start_time) * 1000)
            
            logger.info(f"✅ Transcription completed: '{full_text[:50]}...' ({processing_time}ms)")
            
            return {
                "text": full_text,
                "language": info.language if hasattr(info, 'language') else language,
                "language_probability": getattr(info, 'language_probability', 0.0),
                "segments": [
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text.strip(),
                        "confidence": getattr(segment, 'avg_logprob', None)
                    } for segment in segment_list
                ],
                "processing_time_ms": processing_time,
                "performance_metrics": {
                    "beam_size": actual_beam_size,
                    "vad_enabled": use_vad,
                    "temperature": temperature,
                    "chunks_processed": len(segment_list),
                    "start_cpu_percent": psutil.cpu_percent(),
                    "end_cpu_percent": psutil.cpu_percent(),
                    "start_gpu_memory_mb": 0,
                    "end_gpu_memory_mb": 0
                }
            }
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
            logger.error(f"❌ Transcription failed after {processing_time}ms: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
        finally:
            with self._lock:
                self.active_requests -= 1

    async def cleanup(self):
        logger.info("🧹 Cleaning up Whisper service resources...")
        if self.model:
            del self.model
            self.model = None
        self.clear_gpu_cache()
        self.is_ready.clear()
        logger.info("✅ Whisper service cleanup completed")

whisper_service = WhisperService()

# Background Tasks
async def cleanup_old_transcripts():
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=config.TRANSCRIPT_RETENTION_HOURS)
        to_remove = [
            transcript_id for transcript_id, transcript in transcript_storage.items()
            if transcript.timestamp < cutoff_time
        ]
        
        for transcript_id in to_remove:
            del transcript_storage[transcript_id]
            
        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} old transcripts")
    except Exception as e:
        logger.error(f"❌ Error during transcript cleanup: {e}")

async def periodic_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await cleanup_old_transcripts()
        except asyncio.CancelledError:
            logger.info("🛑 Cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup: {e}")

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    global cleanup_task, processing_semaphore
    
    logger.info("🚀 Starting June STT Service v3.1.1 (Fixed Orchestrator Integration)")
    logger.info(f"🔧 Config: Model={config.WHISPER_MODEL}, Device={config.WHISPER_DEVICE}, Compute={config.WHISPER_COMPUTE_TYPE}")
    
    processing_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
    
    # Initialize Faster-Whisper model
    logger.info("🔄 Initializing Faster-Whisper model...")
    try:
        await whisper_service.initialize()
        logger.info("✅ Model initialization completed successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Faster-Whisper service: {e}")
    
    cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info("✅ June STT Service started successfully")
    
    yield
    
    logger.info("🛑 Shutting down June STT Service")
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    await whisper_service.cleanup()
    logger.info("✅ Shutdown completed")

# FastAPI app
app = FastAPI(
    title="June STT Service (Fixed Orchestrator)", 
    version="3.1.1", 
    description="Speech-to-Text with proper orchestrator integration",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request validation
async def validate_audio_file(audio_file: UploadFile) -> None:
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
    return {
        "service": "June STT Service (Fixed Orchestrator)",
        "version": "3.1.1", 
        "status": "healthy" if whisper_service.is_model_ready() else "initializing",
        "whisper_model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "compute_type": config.WHISPER_COMPUTE_TYPE,
        "auth_available": AUTH_AVAILABLE,
        "beam_size": config.WHISPER_BEAM_SIZE,
        "orchestrator_integration": "enabled",
        "endpoints": {
            "transcribe": "/v1/transcribe",
            "health": "/healthz",
            "ready": "/ready"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-stt",
        "version": "3.1.1",
        "timestamp": datetime.utcnow().isoformat(),
        "model_ready": whisper_service.is_model_ready(),
        "active_requests": whisper_service.active_requests
    }

@app.get("/ready")
async def readiness_check():
    if whisper_service.is_model_ready():
        return {
            "status": "ready",
            "model_loaded": True,
            "service": "june-stt",
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
    temperature: Optional[float] = Form(0.0),
    beam_size: Optional[int] = Form(None),
    use_vad: Optional[bool] = Form(False),
    notify_orchestrator: Optional[bool] = Form(True),
    auth_data: dict = Depends(require_user_auth)
):
    """
    Transcribe audio and send to orchestrator
    
    FIXED: Now properly uses the new orchestrator_client.py
    """
    async with processing_semaphore:
        user_id = extract_user_id(auth_data)
        
        await validate_audio_file(audio_file)
        
        # Ensure model is ready
        if not whisper_service.is_model_ready():
            if not whisper_service.is_loading:
                logger.info("🔄 Loading Faster-Whisper model on demand...")
                await whisper_service.initialize()
            
            logger.info("⏳ Waiting for model to be ready...")
            ready = await whisper_service.wait_for_ready(timeout=60.0)
            if not ready:
                raise HTTPException(status_code=503, detail="Model loading timeout")
        
        try:
            transcript_id = str(uuid.uuid4())
            os.makedirs("/tmp", exist_ok=True)
            
            # Save uploaded file temporarily
            file_path = f"/tmp/june_stt_{transcript_id}_{audio_file.filename}"
            try:
                with open(file_path, "wb") as f:
                    content = await audio_file.read()
                    f.write(content)
                
                logger.info(f"🎵 Starting transcription for {audio_file.filename} ({len(content)} bytes)")
                
                # Simple transcription using faster-whisper
                result = await whisper_service.transcribe(
                    file_path, 
                    language=language, 
                    task=task, 
                    temperature=temperature,
                    beam_size=beam_size,
                    use_vad=use_vad
                )
                
                # Create transcript result
                transcript_result = TranscriptionResult(
                    transcript_id=transcript_id,
                    text=result["text"],
                    language=result.get("language"),
                    confidence=result.get("language_probability"),
                    processing_time_ms=result["processing_time_ms"],
                    timestamp=datetime.utcnow(),
                    status="completed",
                    user_id=user_id,
                    segments=result.get("segments", []),
                    performance_metrics=result.get("performance_metrics", {})
                )
                
                # Store transcript in memory
                transcript_storage[transcript_id] = transcript_result
                
                # FIXED: Notify orchestrator using the new client
                if notify_orchestrator:
                    try:
                        orchestrator_client = get_orchestrator_client()
                        
                        notification_data = {
                            "transcript_id": transcript_id,
                            "user_id": user_id,
                            "text": result["text"],  # THIS IS WHAT USER SAID
                            "language": result.get("language"),
                            "confidence": result.get("language_probability"),
                            "processing_time_ms": result["processing_time_ms"],
                            "metadata": {
                                "task": task,
                                "filename": audio_file.filename,
                                "engine": "faster-whisper",
                                "model": config.WHISPER_MODEL,
                                "beam_size": result["performance_metrics"].get("beam_size"),
                                "vad_enabled": use_vad
                            }
                        }
                        
                        # Send to orchestrator in background
                        background_tasks.add_task(
                            orchestrator_client.notify_transcript,
                            notification_data
                        )
                        
                        logger.info(f"📤 Queued orchestrator notification for transcript {transcript_id}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to queue orchestrator notification: {e}")
                        # Don't fail the request if orchestrator notification fails
                
                logger.info(f"✅ Transcription completed: {transcript_id} for user {user_id} ({result['processing_time_ms']}ms)")
                
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
            logger.error(f"❌ Transcription error: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "june-stt"
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
            "service": "june-stt"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")