"""
June Orchestrator - Janus WebRTC Edition
Coordinates between Janus WebRTC, STT, TTS, and AI services
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup/shutdown"""
    logger.info("🚀 June Orchestrator v12.0.0 - Janus WebRTC Edition")
    logger.info(f"🔧 Environment: {config.environment}")
    logger.info(f"🔧 Janus Gateway: webrtc.ozzu.world")
    logger.info(f"🔧 TTS: {config.services.tts_base_url}")
    logger.info(f"🔧 STT: {config.services.stt_base_url}")
    yield
    logger.info("🛑 Shutting down...")

# Create FastAPI app
app = FastAPI(
    title="June Orchestrator",
    version="12.0.0", 
    description="AI Voice Chat Orchestrator with Janus WebRTC",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple routes without external dependencies
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "12.0.0",
        "status": "running",
        "webrtc": "janus",
        "features": {
            "janus_webrtc": True,
            "ai": bool(config.services.gemini_api_key),
            "tts": bool(config.services.tts_base_url),
            "stt": bool(config.services.stt_base_url)
        }
    }

@app.get("/healthz")
async def healthz():
    """Kubernetes health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "12.0.0"
    }


@app.get("/api/webrtc/config")
async def webrtc_config():
    """WebRTC configuration for frontend"""
    return {
        "janus": {
            "url": "https://janus.ozzu.world/janus",
            "websocket": "wss://webrtc.ozzu.world/ws"
        },
        "ice_servers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {
                "urls": "turn:31449", # NodePort from STUNner
                "username": "june-user",
                "credential": "Pokemon123!"
            }
        ]
    }

@app.get("/readyz")
async def readyz():
    """Kubernetes readiness check endpoint"""
    return {
        "status": "ready",
        "service": "june-orchestrator"
    }

@app.post("/api/voice/process")
async def process_voice():
    """Voice processing endpoint"""
    return {"message": "Voice processing with Janus + STT/TTS"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
