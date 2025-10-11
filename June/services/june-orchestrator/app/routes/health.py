"""
Health Check Endpoints
"""
import logging
from datetime import datetime
from fastapi import APIRouter

from ..config import config
from ..livekit.config import livekit_config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/healthz")
async def health_check():
    """Kubernetes liveness probe"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "11.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/readyz")
async def readiness_check():
    """Kubernetes readiness probe"""
    checks = {
        "livekit": livekit_config.is_configured,
        "ai": bool(config.services.gemini_api_key),
        "tts": bool(config.services.tts_base_url),
        "stt": bool(config.services.stt_base_url)
    }
    
    all_ready = all(checks.values())
    
    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/status")
async def get_status():
    """Detailed status information"""
    return {
        "orchestrator": "healthy",
        "version": "11.0.0",
        "environment": config.environment,
        "features": {
            "livekit": {
                "enabled": livekit_config.is_configured,
                "url": livekit_config.url if livekit_config.is_configured else None
            },
            "ai": {
                "enabled": bool(config.services.gemini_api_key),
                "provider": "gemini"
            },
            "tts": {
                "enabled": bool(config.services.tts_base_url),
                "url": config.services.tts_base_url
            },
            "stt": {
                "enabled": bool(config.services.stt_base_url),
                "url": config.services.stt_base_url
            }
        },
        "timestamp": datetime.utcnow().isoformat()
    }