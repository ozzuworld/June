"""
Updated main.py - Changes to make

ONLY CHANGE THE LIFESPAN FUNCTION - rest stays the same
"""
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .core.dependencies import get_session_service, get_config
from .routes.webhooks import router as webhooks_router
from .routes.xtts_voices import router as voices_router
from .routes.livekit_token import router as livekit_router
from .routes.vpn import router as vpn_router

# ✅ ADD THIS IMPORT
from .services.simple_assistant import initialize_assistant

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
    """
    Application lifespan - UPDATED FOR SIMPLE ASSISTANT
    
    CHANGES FROM OLD VERSION:
    - Removed: RealTimeConversationEngine initialization
    - Removed: StreamingAIService initialization  
    - Removed: SmartTTSQueue initialization
    - Added: SimpleVoiceAssistant initialization
    """
    logger.info("=" * 80)
    logger.info("🚀 June Orchestrator - SIMPLE VOICE ASSISTANT")
    logger.info("=" * 80)
    
    # Initialize core services
    session_service = get_session_service()
    
    logger.info(f"🔧 Configuration:")
    logger.info(f"  TTS: {config.services.tts_base_url}")
    logger.info(f"  STT: {config.services.stt_base_url}")
    logger.info(f"  LiveKit: {config.livekit.ws_url}")
    logger.info(f"  AI Model: {config.ai.model}")
    
    # ✅ NEW: Initialize simple assistant
    logger.info("\n🎙️ Initializing Simple Voice Assistant...")
    try:
        initialize_assistant()
        logger.info("✅ Simple Voice Assistant ready")
    except Exception as e:
        logger.error(f"❌ Failed to initialize assistant: {e}")
        raise
    
    logger.info("\n✨ SIMPLE PIPELINE:")
    logger.info("  ✅ Direct STT → LLM → TTS flow")
    logger.info("  ✅ No buffering queues")
    logger.info("  ✅ No complex state management")
    logger.info("  ✅ Sentence-based TTS chunking")
    logger.info("  ✅ In-memory conversation history")
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
    version="10.0.0-SIMPLE",
    description="AI Voice Assistant with Simple Architecture",
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
app.include_router(voices_router, tags=["XTTS Voices"])
app.include_router(livekit_router, tags=["LiveKit"])
app.include_router(vpn_router, tags=["VPN"])


@app.get("/")
async def root():
    """Root endpoint with system info"""
    from .services.simple_assistant import get_assistant
    
    assistant = get_assistant()
    stats = assistant.get_stats()
    
    return {
        "service": "june-orchestrator",
        "version": "10.0.0-SIMPLE",
        "description": "AI Voice Assistant with Simple Architecture",
        "architecture": "simple",
        "pipeline": "STT → LLM → TTS",
        "features": {
            "direct_flow": True,
            "sentence_chunking": True,
            "conversation_memory": True,
            "low_latency": True,
            "simple_codebase": True
        },
        "stats": stats
    }


@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    try:
        from .services.simple_assistant import get_assistant
        
        assistant = get_assistant()
        health = await assistant.health_check()
        
        return {
            "status": "healthy",
            "service": "june-orchestrator",
            "version": "10.0.0-SIMPLE",
            "assistant": health
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "june-orchestrator",
            "error": str(e)
        }