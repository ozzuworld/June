"""Simplified main.py - Essential services only"""
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .core.dependencies import get_session_service, get_config
from .routes.webhooks import router as webhooks_router
from .routes.voices import router as voices_router
from .routes.livekit_token import router as livekit_router
from .voice_registry import get_available_voices

config = get_config()

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BodyLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info(
            f"[REQUEST] {request.method} {request.url.path} "
            f"CT={request.headers.get('content-type')} "
            f"CL={request.headers.get('content-length')}"
        )
        response = await call_next(request)
        return response


async def cleanup_sessions_task():
    """Background cleanup task"""
    session_service = get_session_service()
    
    while True:
        try:
            await asyncio.sleep(config.sessions.cleanup_interval_minutes * 60)
            logger.info("🧹 Running session cleanup...")
            
            cleaned = session_service.cleanup_expired_sessions(
                timeout_hours=config.sessions.session_timeout_hours
            )
            
            if cleaned > 0:
                logger.info(f"✅ Cleaned {cleaned} expired sessions")
            
            stats = session_service.get_stats()
            logger.info(
                f"📊 Active sessions: {stats.active_sessions}, "
                f"Total created: {stats.total_sessions_created}"
            )
            
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - simplified"""
    logger.info("=" * 80)
    logger.info("🚀 June Orchestrator - STREAMLINED VERSION")
    logger.info("=" * 80)
    
    # Initialize core services
    session_service = get_session_service()
    
    logger.info(f"🔧 Configuration:")
    logger.info(f"  TTS: {config.services.tts_base_url}")
    logger.info(f"  STT: {config.services.stt_base_url}")
    logger.info(f"  LiveKit: {config.livekit.ws_url}")
    logger.info(f"  AI Model: {config.ai.model}")
    
    voices = get_available_voices()
    logger.info(f"🎭 Voices: {len(voices)} available")
    
    logger.info("✨ STREAMLINED:")
    logger.info("  ✅ Single RT engine (no duplication)")
    logger.info("  ✅ No Redis preprocessing (no failures)")
    logger.info("  ✅ Direct STT → AI → TTS flow")
    logger.info("  ✅ SmartTTSQueue for natural timing")
    logger.info("=" * 80)
    
    # Start background cleanup
    cleanup_task = asyncio.create_task(cleanup_sessions_task())
    logger.info("✅ Background tasks started")
    
    yield
    
    # Shutdown
    cleanup_task.cancel()
    logger.info("🛑 Shutting down...")
    stats = session_service.get_stats()
    logger.info(f"📊 Final stats: {stats.active_sessions} active sessions")


app = FastAPI(
    title="June Orchestrator",
    version="8.0.0-STREAMLINED",
    description="Simplified AI Voice Assistant",
    lifespan=lifespan
)

# Middleware
app.add_middleware(BodyLoggerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(webhooks_router, tags=["Webhooks"])
app.include_router(voices_router, tags=["Voices"])
app.include_router(livekit_router, tags=["LiveKit"])


@app.get("/")
async def root():
    session_service = get_session_service()
    stats = session_service.get_stats()
    
    return {
        "service": "june-orchestrator",
        "version": "8.0.0-STREAMLINED",
        "description": "Simplified AI Voice Assistant",
        "streamlined": True,
        "features": {
            "single_rt_engine": True,
            "no_redis_preprocessing": True,
            "smart_tts_queue": True,
            "natural_conversation": True
        },
        "stats": {
            "active_sessions": stats.active_sessions,
            "total_sessions": stats.total_sessions_created,
            "total_messages": stats.total_messages
        }
    }


@app.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "8.0.0-STREAMLINED"
    }