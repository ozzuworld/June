# June/services/june-stt/app.py
# Enhanced STT microservice with Keycloak authentication (based on TTS pattern)

import os
import time
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path

import httpx
import whisper
import torch
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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

app = FastAPI(title="June STT Service", version="2.0.0", description="Speech-to-Text microservice with Keycloak authentication")

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with your frontend domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
whisper_model = None
transcript_storage = {}  # In-memory storage for transcripts
processing_queue = asyncio.Queue()

# Configuration
class Config:
    # Orchestrator
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")
    ORCHESTRATOR_API_KEY = os.getenv("ORCHESTRATOR_API_KEY", "")
    
    # Whisper
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Storage
    TRANSCRIPT_RETENTION_HOURS = int(os.getenv("TRANSCRIPT_RETENTION_HOURS", "24"))

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

class TranscriptionRequest(BaseModel):
    language: Optional[str] = None
    task: Optional[str] = "transcribe"  # transcribe or translate
    temperature: Optional[float] = 0.0
    notify_orchestrator: Optional[bool] = True

class TranscriptNotification(BaseModel):
    transcript_id: str
    user_id: str
    text: str
    timestamp: datetime
    metadata: Dict[str, Any] = {}

# Whisper Service
class WhisperService:
    def __init__(self):
        self.model = None
        self.device = config.WHISPER_DEVICE
        
    async def initialize(self):
        """Initialize Whisper model"""
        try:
            logger.info(f"🔄 Loading Whisper model {config.WHISPER_MODEL} on {self.device}")
            self.model = whisper.load_model(config.WHISPER_MODEL, device=self.device)
            logger.info("✅ Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            raise
    
    async def transcribe(self, audio_file_path: str, language: Optional[str] = None, 
                        task: str = "transcribe", temperature: float = 0.0) -> Dict[str, Any]:
        """Transcribe audio file"""
        if not self.model:
            raise HTTPException(status_code=500, detail="Whisper model not initialized")
        
        try:
            start_time = time.time()
            
            # Configure options
            options = {
                "fp16": self.device == "cuda",
                "language": language,
                "task": task,
                "temperature": temperature
            }
            
            # Remove None values
            options = {k: v for k, v in options.items() if v is not None}
            
            # Run transcription
            result = self.model.transcribe(audio_file_path, **options)
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return {
                "text": result["text"].strip(),
                "language": result.get("language"),
                "segments": result.get("segments", []),
                "processing_time_ms": processing_time
            }
        except Exception as e:
            logger.error(f"❌ Transcription failed: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

whisper_service = WhisperService()

# Orchestrator Client
class OrchestratorClient:
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.api_key = config.ORCHESTRATOR_API_KEY
    
    async def notify_transcript(self, notification: TranscriptNotification):
        """Send transcript notification to orchestrator"""
        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/transcripts",
                    json=notification.dict(),
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Notified orchestrator about transcript {notification.transcript_id}")
                else:
                    logger.warning(f"⚠️ Orchestrator notification failed: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to notify orchestrator: {e}")

orchestrator_client = OrchestratorClient()

# Background Tasks
async def cleanup_old_transcripts():
    """Clean up old transcripts from memory"""
    cutoff_time = datetime.utcnow() - timedelta(hours=config.TRANSCRIPT_RETENTION_HOURS)
    
    to_remove = []
    for transcript_id, transcript in transcript_storage.items():
        if transcript.timestamp < cutoff_time:
            to_remove.append(transcript_id)
    
    for transcript_id in to_remove:
        del transcript_storage[transcript_id]
        logger.info(f"🗑️ Cleaned up old transcript: {transcript_id}")

# API Endpoints
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting June STT Service v2.0.0")
    
    # Initialize Whisper model
    await whisper_service.initialize()
    
    # Start background cleanup task
    asyncio.create_task(periodic_cleanup())
    
    logger.info("✅ June STT Service started successfully")

async def periodic_cleanup():
    """Periodically clean up old transcripts"""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        await cleanup_old_transcripts()

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "June STT Service",
        "version": "2.0.0",
        "status": "healthy",
        "whisper_model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "auth_available": AUTH_AVAILABLE,
        "endpoints": {
            "transcribe": "/v1/transcribe",
            "transcripts": "/v1/transcripts/{transcript_id}",
            "health": "/healthz"
        }
    }

@app.get("/healthz")
async def health_check():
    """Health check for Kubernetes/Docker"""
    model_status = "ready" if whisper_service.model else "loading"
    return {
        "status": "healthy",
        "service": "june-stt",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "whisper_model_status": model_status,
        "auth_status": "keycloak" if AUTH_AVAILABLE else "fallback"
    }

@app.post("/v1/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = None,
    task: Optional[str] = "transcribe",
    temperature: Optional[float] = 0.0,
    notify_orchestrator: Optional[bool] = True,
    auth_data: dict = Depends(require_user_auth)
):
    """
    Transcribe uploaded audio file
    
    - **audio_file**: Audio file (wav, mp3, m4a, etc.)
    - **language**: Source language (optional, auto-detected if not provided)  
    - **task**: 'transcribe' or 'translate' (to English)
    - **temperature**: Sampling temperature (0.0 = deterministic)
    - **notify_orchestrator**: Whether to notify orchestrator service
    """
    start_time = time.time()
    user_id = extract_user_id(auth_data)
    
    try:
        # Validate file type
        if not audio_file.content_type or not audio_file.content_type.startswith(('audio/', 'video/')):
            raise HTTPException(status_code=400, detail="File must be audio or video format")
        
        # Generate unique transcript ID
        transcript_id = str(uuid.uuid4())
        
        # Save uploaded file temporarily
        file_path = f"/tmp/june_stt_{transcript_id}_{audio_file.filename}"
        try:
            with open(file_path, "wb") as f:
                content = await audio_file.read()
                f.write(content)
            
            # Transcribe audio
            result = await whisper_service.transcribe(
                file_path, 
                language=language, 
                task=task, 
                temperature=temperature
            )
            
            # Create transcript result
            transcript_result = TranscriptionResult(
                transcript_id=transcript_id,
                text=result["text"],
                language=result.get("language"),
                processing_time_ms=result["processing_time_ms"],
                timestamp=datetime.utcnow(),
                status="completed",
                user_id=user_id
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
                        "task": task
                    }
                )
                background_tasks.add_task(orchestrator_client.notify_transcript, notification)
            
            logger.info(f"✅ Transcription completed: {transcript_id} for user {user_id} ({result['processing_time_ms']}ms)")
            
            return transcript_result
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(file_path)
            except:
                pass
                
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
    """Get transcript by ID"""
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
    auth_data: dict = Depends(require_user_auth)
):
    """List recent transcripts for user"""
    user_id = extract_user_id(auth_data)
    
    # Filter transcripts by user
    user_transcripts = [
        transcript for transcript in transcript_storage.values()
        if transcript.user_id == user_id
    ]
    
    user_transcripts.sort(key=lambda x: x.timestamp, reverse=True)
    
    return {
        "transcripts": user_transcripts[:limit],
        "total": len(user_transcripts)
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
    """Get service statistics"""
    user_id = extract_user_id(auth_data)
    user_transcripts = [t for t in transcript_storage.values() if t.user_id == user_id]
    
    return {
        "user_transcripts": len(user_transcripts),
        "total_transcripts": len(transcript_storage),
        "whisper_model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "auth_provider": "keycloak" if AUTH_AVAILABLE else "fallback"
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return {"error": exc.detail, "status_code": exc.status_code}

if __name__ == "__main__":
    import uvicorn
    startup_time = time.time()
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
