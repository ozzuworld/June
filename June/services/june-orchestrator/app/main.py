import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .routes.webhooks import router as webhooks_router
from .routes.voices import router as voices_router
from .routes_livekit import router as livekit_router
from .session_manager import session_manager
from .services.skill_service import skill_service
from .services.voice_profile_service import voice_profile_service
from .security.rate_limiter import rate_limiter, duplication_detector
from .security.cost_tracker import call_tracker, circuit_breaker
from .config import config
from .voice_registry import get_available_voices, resolve_voice_reference

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
            
            # Log skill usage
            if stats.get("active_skills", 0) > 0:
                logger.info(f"🤖 Active skills: {stats.get('skills_in_use', {})}")
            
        except Exception as e:
            logger.error(f"❌ Session cleanup task error: {e}")


# SECURITY: Background task for security monitoring
async def security_monitoring_task():
    """Background task to monitor security metrics and costs"""
    while True:
        try:
            await asyncio.sleep(300)  # Every 5 minutes
            
            # Get security stats
            cost_stats = call_tracker.get_stats()
            rate_stats = rate_limiter.get_stats()
            circuit_status = circuit_breaker.get_status()
            
            # Log cost warnings
            if cost_stats['daily_cost'] > 25.0:  # $25 warning threshold
                logger.warning(
                    f"💰 HIGH COST WARNING: ${cost_stats['daily_cost']:.2f} spent today "
                    f"({cost_stats['utilization']['cost_percent']:.1f}% of limit)"
                )
            
            # Log rate limiting activity
            if rate_stats['blocked_users'] > 0:
                logger.warning(
                    f"🚫 RATE LIMITING ACTIVE: {rate_stats['blocked_users']} users blocked"
                )
            
            # Log circuit breaker status
            if circuit_status['is_open']:
                logger.error(
                    f"🚨 CIRCUIT BREAKER OPEN: Service degraded "
                    f"(failures: {circuit_status['failure_count']})"
                )
            
            # Periodic security summary (every hour)
            if asyncio.get_event_loop().time() % 3600 < 300:  # Rough hourly check
                logger.info(
                    f"🔒 Security Summary: "
                    f"${cost_stats['daily_cost']:.2f} spent, "
                    f"{cost_stats['daily_calls']} AI calls, "
                    f"{rate_stats['total_users_tracked']} users tracked, "
                    f"Circuit: {'OPEN' if circuit_status['is_open'] else 'CLOSED'}"
                )
            
        except Exception as e:
            logger.error(f"❌ Security monitoring error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with enhanced startup and background tasks"""
    logger.info("=" * 70)
    logger.info("🚀 June Orchestrator v7.1 - AI Voice Assistant with Chatterbox TTS")
    logger.info("=" * 70)
    
    # Core configuration
    logger.info(f"🔧 Core Configuration:")
    logger.info(f"  TTS Service: {config.services.tts_base_url}")
    logger.info(f"  STT Service: {config.services.stt_base_url}")
    logger.info(f"  LiveKit: {config.livekit.ws_url}")
    
    # AI configuration
    logger.info(f"🤖 AI Configuration:")
    logger.info(f"  Model: {config.ai.model}")
    logger.info(f"  Voice Mode: {config.ai.voice_response_mode}")
    logger.info(f"  Max Output Tokens: {config.ai.max_output_tokens}")
    
    # Voice configuration
    voices = get_available_voices()
    default_voice_ref = resolve_voice_reference(None, None)
    logger.info(f"🎭 Voice Configuration:")
    logger.info(f"  Available Voices: {len(voices)}")
    logger.info(f"  Voice Registry: {list(voices.keys())[:3]}...")
    logger.info(f"  Default Voice: {default_voice_ref}")
    
    # Session configuration
    logger.info(f"📝 Session Configuration:")
    logger.info(f"  Max History: {config.sessions.max_history_messages} messages")
    logger.info(f"  Session Timeout: {config.sessions.session_timeout_hours} hours")
    
    # SECURITY configuration
    logger.info(f"🔒 Security Configuration:")
    logger.info(f"  Rate Limiting: {rate_limiter.ai_calls_per_minute}/min, {rate_limiter.ai_calls_per_hour}/hour")
    logger.info(f"  Daily Cost Limit: ${call_tracker.max_daily_cost}")
    logger.info(f"  Daily Call Limit: {call_tracker.max_daily_calls}")
    logger.info(f"  Circuit Breaker: {'Enabled' if not circuit_breaker.is_open else 'OPEN'}")
    
    # Skill system
    skills = skill_service.list_skills()
    logger.info(f"🎭 Skill System:")
    logger.info(f"  Available Skills: {list(skills.keys())}")
    logger.info(f"  Ready Skills: ['mockingbird']")
    logger.info(f"  Voice Profiles: {len(voice_profile_service.profiles)}")
    
    logger.info("=" * 70)
    
    # Start background tasks
    cleanup_task = asyncio.create_task(cleanup_sessions_task())
    security_task = asyncio.create_task(security_monitoring_task())
    logger.info("✅ Background tasks started (cleanup + security monitoring)")
    
    yield
    
    # Cleanup on shutdown
    cleanup_task.cancel()
    security_task.cancel()
    logger.info("🛑 Shutting down...")
    logger.info(f"📊 Final session stats: {session_manager.get_stats()}")
    logger.info(f"🎭 Final voice profile stats: {voice_profile_service.get_stats()}")
    logger.info(f"💰 Final cost stats: {call_tracker.get_stats()}")


app = FastAPI(
    title="June Orchestrator",
    version="7.1.0-CHATTERBOX",
    description="AI Voice Assistant Orchestrator with Skills, Voice Cloning, Security Protection, and Chatterbox TTS",
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
app.include_router(webhooks_router, tags=["Webhooks & Skills & Security"])
app.include_router(voices_router, tags=["Voice Management"])
app.include_router(livekit_router, tags=["LiveKit"])


@app.get("/")
async def root():
    stats = session_manager.get_stats()
    skills = skill_service.list_skills()
    voice_stats = voice_profile_service.get_stats()
    voices = get_available_voices()
    security_stats = {
        "rate_limiter": rate_limiter.get_stats(),
        "duplication_detector": duplication_detector.get_stats(),
        "cost_tracker": call_tracker.get_stats(),
        "circuit_breaker": circuit_breaker.get_status()
    }
    
    return {
        "service": "june-orchestrator",
        "version": "7.1.0-CHATTERBOX",
        "description": "AI Voice Assistant Orchestrator with Skills, Voice Cloning, Security Protection, and Chatterbox TTS",
        "features": [
            "✅ Conversation Memory",
            "✅ Context Management",
            "✅ Room-to-Session Mapping",
            "✅ Voice-Optimized AI",
            "✅ Skill-Based Architecture",
            "✅ Voice Cloning Skills",
            "✅ Session Cleanup",
            "🔒 SECURITY: Rate Limiting",
            "🔒 SECURITY: Duplicate Detection",
            "🔒 SECURITY: Cost Tracking",
            "🔒 SECURITY: Circuit Breaker",
            "🎭 NEW: Chatterbox TTS Integration",
            "🎭 NEW: Voice Registry & Emotion Controls"
        ],
        "skills": {
            "available": list(skills.keys()),
            "ready": ["mockingbird"],
            "coming_soon": ["translator", "storyteller"]
        },
        "endpoints": {
            "livekit": "/api/livekit/token",
            "stt_webhook": "/api/webhooks/stt",
            "skills": "/api/skills",
            "skills_help": "/api/skills/help",
            "session_history": "/api/sessions/{id}/history",
            "session_stats": "/api/sessions/stats",
            "security_stats": "/api/security/stats",
            "circuit_breaker_open": "/api/security/circuit-breaker/open",
            "circuit_breaker_close": "/api/security/circuit-breaker/close",
            "voices": "/api/voices",
            "voice_warmup": "/api/voices/warmup",
            "voice_resolve": "/api/voices/resolve",
            "tts_publish": "/api/tts/publish",
            "health": "/healthz"
        },
        "stats": stats,
        "voice_profiles": voice_stats,
        "voice_registry": {
            "available_voices": list(voices.keys()),
            "total_voices": len(voices),
            "default_voice": resolve_voice_reference(None, None)
        },
        "security": security_stats,
        "config": {
            "ai_model": config.ai.model,
            "voice_mode": config.ai.voice_response_mode,
            "max_history": config.sessions.max_history_messages,
            "livekit_url": config.livekit.ws_url,
            "skills_enabled": True,
            "security_enabled": True,
            "daily_cost_limit": call_tracker.max_daily_cost,
            "ai_rate_limits": {
                "per_minute": rate_limiter.ai_calls_per_minute,
                "per_hour": rate_limiter.ai_calls_per_hour
            },
            "tts_engine": "chatterbox-tts",
            "voice_controls": {
                "emotion_control": True,
                "pacing_control": True,
                "voice_cloning": True
            }
        }
    }


@app.get("/healthz")
async def healthz():
    stats = session_manager.get_stats()
    cost_stats = call_tracker.get_stats()
    circuit_status = circuit_breaker.get_status()
    voices = get_available_voices()
    
    # Determine health status
    is_healthy = True
    health_issues = []
    
    if circuit_status["is_open"]:
        is_healthy = False
        health_issues.append("Circuit breaker is open")
    
    if cost_stats["utilization"]["cost_percent"] > 90:
        is_healthy = False
        health_issues.append(f"High cost utilization: {cost_stats['utilization']['cost_percent']:.1f}%")
    
    if cost_stats["remaining_calls"] < 50:
        is_healthy = False
        health_issues.append(f"Low remaining API calls: {cost_stats['remaining_calls']}")
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "service": "june-orchestrator",
        "version": "7.1.0-CHATTERBOX",
        "issues": health_issues,
        "stats": stats,
        "voice_registry": {
            "available_voices": len(voices),
            "default_voice": resolve_voice_reference(None, None)
        },
        "security": {
            "circuit_breaker_open": circuit_status["is_open"],
            "daily_cost": cost_stats["daily_cost"],
            "remaining_budget": cost_stats["remaining_cost"],
            "cost_utilization_percent": cost_stats["utilization"]["cost_percent"],
            "daily_calls": cost_stats["daily_calls"],
            "remaining_calls": cost_stats["remaining_calls"]
        },
        "features": {
            "memory": True,
            "context_management": True,
            "voice_optimized": config.ai.voice_response_mode,
            "ai_configured": bool(config.services.gemini_api_key),
            "skills_system": True,
            "voice_cloning": True,
            "security_protection": True,
            "rate_limiting": True,
            "duplicate_detection": True,
            "cost_tracking": True,
            "circuit_breaker": True,
            "chatterbox_tts": True,
            "emotion_controls": True
        }
    }