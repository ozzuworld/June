"""
Simplified June STT Service - Following best practices
"""
import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from whisper_service import whisper_service
from orchestrator_client import orchestrator_client

# Simplified logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Simple auth fallback
async def simple_auth(authorization: str = Header(None)) -> Dict[str, str]:
    """Simplified authentication"""
    return {"user_id": "fallback_user"}

# Response model
class TranscriptionResponse(BaseModel):
    transcript_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    processing_time_ms: int
    timestamp: datetime

# App lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting June STT Service v4.0.0 (Optimized)")
    
    # Initialize model
    try:
        await whisper_service.initialize()
        logger.info("✅ Service ready")
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
    
    yield
    
    logger.info("🛑 Shutting down")
    whisper_service.cleanup()

# FastAPI app
app = FastAPI(
    title="June STT Service (Optimized)", 
    version="4.0.0", 
    description="Simplified, optimized speech-to-text service",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/")
async def root():
    return {
        "service": "June STT Service (Optimized)",
        "version": "4.0.0",
        "status": "ready" if whisper_service.is_model_ready() else "initializing",
        "model": config.WHISPER_MODEL,
        "device": config.WHISPER_DEVICE,
        "compute_type": config.WHISPER_COMPUTE_TYPE
    }

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "service": "june-stt",
        "version": "4.0.0",
        "model_ready": whisper_service.is_model_ready()
    }

@app.post("/v1/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    auth_data: dict = Depends(simple_auth)
):
    """
    Simplified transcription endpoint
    """
    # Validate file
    if not audio_file.content_type or not audio_file.content_type.startswith(('audio/', 'video/')):
        raise HTTPException(status_code=400, detail="File must be audio or video")
    
    max_size = config.MAX_FILE_SIZE_MB * 1024 * 1024
    if audio_file.size and audio_file.size > max_size:
        raise HTTPException(status_code=413, detail=f"File too large (max {config.MAX_FILE_SIZE_MB}MB)")
    
    # Wait for model if needed
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Model not ready")
    
    try:
        transcript_id = str(uuid.uuid4())
        
        # Save temp file
        temp_path = f"/tmp/stt_{transcript_id}_{audio_file.filename}"
        try:
            with open(temp_path, "wb") as f:
                content = await audio_file.read()
                f.write(content)
            
            logger.info(f"🎵 Transcribing {audio_file.filename} ({len(content)} bytes)")
            
            # Transcribe
            result = await whisper_service.transcribe(temp_path, language)
            
            # Create response
            response = TranscriptionResponse(
                transcript_id=transcript_id,
                text=result["text"],
                language=result.get("language"),
                confidence=result.get("language_probability"),
                processing_time_ms=result["processing_time_ms"],
                timestamp=datetime.utcnow()
            )
            
            # Notify orchestrator (background)
            if orchestrator_client.enabled:
                notification_data = {
                    "transcript_id": transcript_id,
                    "user_id": auth_data["user_id"],
                    "text": result["text"],
                    "language": result.get("language"),
                    "confidence": result.get("language_probability"),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                background_tasks.add_task(
                    orchestrator_client.notify_transcript,
                    notification_data
                )
            
            logger.info(f"✅ Transcription complete: {transcript_id}")
            return response
            
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
