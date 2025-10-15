import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import config
from .routes import (
    sessions_router,
    livekit_webhooks_router,
    livekit_token_router,
    ai_router,
    health_router
)

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BodyLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Do NOT consume the body; just log headers to avoid interfering with downstream parsing
        try:
            logger.info(
                f"[BODY TAP] {request.method} {request.url.path} "
                f"CT={request.headers.get('content-type')} "
                f"CL={request.headers.get('content-length')}"
            )
        except Exception as e:
            logger.warning(f"[BODY TAP] Header log failed: {e}")
        response = await call_next(request)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    logger.info("🚀 June Orchestrator v3.0 - LiveKit Integration")
    logger.info(f"🔧 TTS: {config.services.tts_base_url}")
    logger.info(f"🔧 STT: {config.services.stt_base_url}")
    logger.info(f"🔧 LiveKit: {config.livekit.ws_url}")
    logger.info(f"🔧 LiveKit API Key: {config.livekit.api_key}")
    logger.info("🎫 LiveKit Token Endpoint: /livekit/token")
    yield
    logger.info("🛑 Shutdown")


app = FastAPI(
    title="June Orchestrator",
    version="3.0.0",
    description="Business logic orchestrator with LiveKit - AI, STT, TTS coordination",
    lifespan=lifespan
)

# Tap request headers only (non-invasive)
app.add_middleware(BodyLoggerMiddleware)

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
app.include_router(livekit_webhooks_router, prefix="/api/livekit-webhooks", tags=["LiveKit Webhooks"])
app.include_router(livekit_token_router, prefix="/livekit", tags=["LiveKit Tokens"])
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])


@app.get("/")
async def root():
    return {
        "service": "june-orchestrator",
        "version": "3.0.0",
        "description": "Business logic orchestrator with LiveKit integration",
        "endpoints": {
            "sessions": "/api/sessions",
            "livekit_webhooks": "/api/livekit-webhooks",
            "livekit_token": "/livekit/token",
            "ai": "/api/ai",
            "health": "/healthz"
        },
        "livekit": {
            "ws_url": config.livekit.ws_url,
            "api_key": config.livekit.api_key
        }
    }