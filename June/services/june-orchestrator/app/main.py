import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .routes.webhooks import router as webhooks_router
from .routes_livekit import router as livekit_router
from .session_manager import session_manager
from .config import config

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BodyLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            logger.info(
                f"[REQUEST] {request.method} {request.url.path} "
                f"CT={request.headers.get('content-type')} "
                f"CL={request.headers.get('content-length')}"
            )
        except Exception as e:
            logger.warning(f"[REQUEST] Header log failed: {e}")
        response = await call_next(request)
        return response


# Background task for session cleanup
async def cleanup_sessions_task():
    """Background task to periodically clean up expired sessions"""
    while True:
        try:
            await asyncio.sleep(config.sessions.cleanup_interval_minutes * 60)
            logger.info("🧹 Running session cleanup task...")
            
            cleaned = session_manager.cleanup_expired_sessions(
                timeout_hours=config.sessions.session_timeout_hours
            )
            
            if cleaned > 0:
                logger.info(f"✅ Cleaned up {cleaned} expired sessions")
            
            # Log stats
            stats = session_manager.get_stats()
            logger.info(f"📊 Session stats: {stats}")
            
        except Exception as e:
            logger.error(f"❌ Session cleanup task error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with enhanced startup and background tasks"""
    logger.info("=" * 60)
    logger.info("🚀 June Orchestrator v5.0 - AI Voice Assistant")
    logger.info("=" * 60)
    logger.info(f"🔧 Configuration:")
    logger.info(f"  TTS: {config.services.tts_base_url}")
    logger.info(f"  STT: {config.services.stt_base_url}")
    logger.info(f"  LiveKit: {config.livekit.ws_url}")
    logger.info(f"  AI Model: {config.ai.model}")
    logger.info(f"  Voice Mode: {config.ai.voice_response_mode}")
    logger.info(f"  Max History: {config.sessions.max_history_messages} messages")
    logger.info(f"  Session Timeout: {config.sessions.session_timeout_hours} hours")
    logger.info("=" * 60)
    
    # Start background tasks
    cleanup_task = asyncio.create_task(cleanup_sessions_task())
    logger.info("✅ Background tasks started")
    
    yield
    
    # Cleanup on shutdown
    cleanup_task.cancel()
    logger.info("🛑 Shutting down...")
    logger.info(f"📊 Final stats: {session_manager.get_stats()}")


app = FastAPI(
    title="June Orchestrator",
    version="5.0.0",
    description="AI Voice Assistant Orchestrator with Memory and Context",
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
app.include_router(livekit_router, tags=["LiveKit"])


@app.get("/")
async def root():
    stats = session_manager.get_stats()
    
    return {
        "service": "june-orchestrator",
        "version": "5.0.0",
        "description": "AI Voice Assistant Orchestrator with Full Memory",
        "features": [
            "✅ Conversation Memory",
            "✅ Context Management",
            "✅ Room-to-Session Mapping",
            "✅ Voice-Optimized AI",
            "✅ Automatic Summarization",
            "✅ Session Cleanup"
        ],
        "endpoints": {
            "livekit": "/api/livekit/token",
            "stt_webhook": "/api/webhooks/stt",
            "session_history": "/api/sessions/{id}/history",
            "session_stats": "/api/sessions/stats",
            "health": "/healthz"
        },
        "stats": stats,
        "config": {
            "ai_model": config.ai.model,
            "voice_mode": config.ai.voice_response_mode,
            "max_history": config.sessions.max_history_messages,
            "livekit_url": config.livekit.ws_url
        }
    }


@app.get("/healthz")
async def healthz():
    stats = session_manager.get_stats()
    
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "5.0.0",
        "stats": stats,
        "features": {
            "memory": True,
            "context_management": True,
            "voice_optimized": config.ai.voice_response_mode,
            "ai_configured": bool(config.services.gemini_api_key)
        }
    }