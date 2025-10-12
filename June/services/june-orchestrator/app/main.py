import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config
from .routes import (
    sessions_router,
    janus_events_router,
    ai_router,
    health_router
)

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    logger.info("🚀 June Orchestrator v2.0 - Business Logic Only")
    logger.info(f"🔧 TTS: {config.services.tts_base_url}")
    logger.info(f"🔧 STT: {config.services.stt_base_url}")
    logger.info(f"🔧 Janus: {config.janus_url}")
    yield
    logger.info("🛑 Shutdown")


app = FastAPI(
    title="June Orchestrator",
    version="2.0.0",
    description="Business logic orchestrator - AI, STT, TTS coordination",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(health_router, tags=["Health"])
app.include_router(sessions_router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(janus_events_router, prefix="/api/janus-events", tags=["Janus Events"])
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])


@app.get("/")
async def root():
    return {
        "service": "june-orchestrator",
        "version": "2.0.0",
        "description": "Business logic only - WebRTC handled by Janus",
        "endpoints": {
            "sessions": "/api/sessions",
            "janus_events": "/api/janus-events",
            "ai": "/api/ai",
            "health": "/healthz"
        }
    }