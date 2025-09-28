# June/services/june-stt/app.py
# Enhanced STT microservice with authentication and orchestrator integration

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
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import firebase_admin
from firebase_admin import credentials, auth
import jwt
from cryptography.hazmat.primitives import serialization

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="June STT Service", version="2.0.0", description="Real-time Speech-to-Text microservice with authentication")

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with your frontend domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Global variables
whisper_model = None
transcript_storage = {}  # In-memory storage for transcripts
processing_queue = asyncio.Queue()

# Configuration
class Config:
    # Authentication
    JWT_SECRET = os.getenv("JWT_SECRET", "june-stt-secret-key-change-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = 24
    
    # Firebase (optional)
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
    
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

class TranscriptionRequest(BaseModel):
    language: Optional[str] = None
    task: Optional[str] = "transcribe"  # transcribe or translate
    temperature: Optional[float] = 0.0
    notify_orchestrator: Optional[bool] = True

class User(BaseModel):
    user_id: str
    email: Optional[str] = None
    roles: List[str] = []

class TranscriptNotification(BaseModel):
    transcript_id: str
    user_id: str
    text: str
    timestamp: datetime
    metadata: Dict[str, Any] = {}

# Authentication Service
class AuthService:
    def __init__(self):
        self.firebase_app = None
        self.setup_firebase()
    
    def setup_firebase(self):
        """Initialize Firebase Admin SDK if credentials are provided"""
        try:
            if config.FIREBASE_CREDENTIALS_PATH and os.path.exists(config.FIREBASE_CREDENTIALS_PATH):
                if not firebase_admin._apps:
                    cred = credentials.Certificate(config.FIREBASE_CREDENTIALS_PATH)
                    self.firebase_app = firebase_admin.initialize_app(cred)
                    logger.info("✅ Firebase Admin SDK initialized")
                else:
                    self.firebase_app = firebase_admin.get_app()
        except Exception as e:
            logger.warning(f"⚠️ Firebase initialization failed: {e}")
            logger.info("📝 Falling back to JWT-only authentication")
    
    def create_jwt_token(self, user_id: str, email: Optional[str] = None) -> str:
        """Create a JWT token for a user"""
        payload = {
            "user_id": user_id,
            "email": email,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=config.JWT_EXPIRATION_HOURS)
        }
        return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    
    async def verify_token(self, token: str) -> User:
        """Verify and decode authentication token"""
        try:
            # Try Firebase token first
            if self.firebase_app:
                try:
                    decoded_token = auth.verify_id_token(token)
                    return User(
                        user_id=decoded_token["uid"],
                        email=decoded_token.get("email"),
                        roles=decoded_token.get("roles", [])
                    )
                except Exception:
                    pass  # Fall through to JWT verification
            
            # Try JWT token
            payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
            return User(
                user_id=payload["user_id"],
                email=payload.get("email"),
                roles=payload.get("roles", [])
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

auth_service = AuthService()

# Dependency to get current user
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Get current authenticated user"""
    return await auth_service.verify_token(credentials.credentials)

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
        "endpoints": {
            "transcribe": "/v1/transcribe",
            "transcripts": "/v1/transcripts/{transcript_id}",
            "auth": "/v1/auth/token"
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
        "whisper_model_status": model_status
    }

@app.post("/v1/auth/token")
async def create_auth_token(user_id: str, email: Optional[str] = None):
    """Create authentication token (for development/testing)"""
    token = auth_service.create_jwt_token(user_id, email)
    return {"access_token": token, "token_type": "bearer"}

@app.post("/v1/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = None,
    task: Optional[str] = "transcribe",
    temperature: Optional[float] = 0.0,
    notify_orchestrator: Optional[bool] = True,
    current_user: User = Depends(get_current_user)
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
                status="completed"
            )
            
            # Store transcript in memory
            transcript_storage[transcript_id] = transcript_result
            
            # Notify orchestrator in background if requested
            if notify_orchestrator:
                notification = TranscriptNotification(
                    transcript_id=transcript_id,
                    user_id=current_user.user_id,
                    text=result["text"],
                    timestamp=transcript_result.timestamp,
                    metadata={
                        "language": result.get("language"),
                        "processing_time_ms": result["processing_time_ms"],
                        "task": task
                    }
                )
                background_tasks.add_task(orchestrator_client.notify_transcript, notification)
            
            logger.info(f"✅ Transcription completed: {transcript_id} ({result['processing_time_ms']}ms)")
            
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
    current_user: User = Depends(get_current_user)
):
    """Get transcript by ID"""
    if transcript_id not in transcript_storage:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    return transcript_storage[transcript_id]

@app.get("/v1/transcripts")
async def list_transcripts(
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """List recent transcripts for user"""
    # In a real implementation, you'd filter by user_id and use proper database
    transcripts = list(transcript_storage.values())
    transcripts.sort(key=lambda x: x.timestamp, reverse=True)
    
    return {
        "transcripts": transcripts[:limit],
        "total": len(transcripts)
    }

@app.delete("/v1/transcripts/{transcript_id}")
async def delete_transcript(
    transcript_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete transcript by ID"""
    if transcript_id not in transcript_storage:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    del transcript_storage[transcript_id]
    return {"message": "Transcript deleted successfully"}

@app.get("/v1/stats")
async def get_stats(current_user: User = Depends(get_current_user)):
    """Get service statistics"""
    return {
        "total_transcripts": len(transcript_storage),
        "whisper_model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "uptime": time.time() - startup_time if 'startup_time' in globals() else 0
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