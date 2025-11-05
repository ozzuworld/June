from fastapi import APIRouter
from . import health, ai, sessions, voices, livekit_token, webhooks, livekit_webhooks

# Include all route modules
api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(ai.router, tags=["ai"])
api_router.include_router(sessions.router, tags=["sessions"])
api_router.include_router(voices.router, tags=["voices"]) 
api_router.include_router(livekit_token.router, tags=["livekit"])
api_router.include_router(webhooks.router, tags=["webhooks"])
api_router.include_router(livekit_webhooks.router, tags=["livekit-webhooks"])