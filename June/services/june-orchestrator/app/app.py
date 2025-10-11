"""
June Orchestrator - Main Application
Slim routing layer - business logic in services/
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config
from .routes import health, chat, livekit_routes, webhooks
from .livekit import livekit_manager, audio_handler, livekit_config
from .services import audio_service

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup/shutdown"""
    logger.info("🚀 June Orchestrator v11.0.0 - LiveKit Edition")
    logger.info(f"🔧 Environment: {config.environment}")
    
    # Initialize services
    if livekit_config.is_configured:
        logger.info("✅ LiveKit enabled")
        logger.info(f"   URL: {livekit_config.url}")
        
        # Wire up audio processing
        audio_handler.set_audio_callback(audio_service.process_livekit_audio)
    else:
        logger.warning("⚠️  LiveKit not configured")
    
    logger.info(f"🔧 TTS: {config.services.tts_base_url}")
    logger.info(f"🔧 STT: {config.services.stt_base_url}")
    logger.info(f"🔧 AI: {'Configured' if config.services.gemini_api_key else 'Not configured'}")
    
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down...")
    if livekit_config.is_configured:
        await audio_handler.cleanup_all()


# Create FastAPI app
app = FastAPI(
    title="June Orchestrator",
    version="11.0.0",
    description="AI Voice Chat Orchestrator with LiveKit",
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

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/v1", tags=["Chat"])
app.include_router(livekit_routes.router, prefix="/v1/livekit", tags=["LiveKit"])
app.include_router(webhooks.router, prefix="/v1", tags=["Webhooks"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "11.0.0",
        "status": "running",
        "features": {
            "livekit": livekit_config.is_configured,
            "ai": bool(config.services.gemini_api_key),
            "tts": bool(config.services.tts_base_url),
            "stt": bool(config.services.stt_base_url)
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower()
    )