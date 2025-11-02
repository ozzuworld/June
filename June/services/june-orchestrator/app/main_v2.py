"""Phase 1 Refactored main.py - Clean Architecture with Dependency Injection"""
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# New clean imports - Phase 1
from .core.dependencies import get_session_service, get_config
from .models.responses import ServiceInfoResponse, HealthResponse

# Existing imports (will be refactored in Phase 2)
from .routes.webhooks import router as webhooks_router
from .routes.voices import router as voices_router
from .routes_livekit import router as livekit_router
from .services.skill_service import skill_service
from .services.voice_profile_service import voice_profile_service
from .security.rate_limiter import rate_limiter, duplication_detector
from .security.cost_tracker import call_tracker, circuit_breaker
from .voice_registry import get_available_voices, resolve_voice_reference

# Get configuration through dependency injection
config = get_config()

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


# PHASE 1: Clean background tasks using dependency injection
async def cleanup_sessions_task():
    """Background task to periodically clean up expired sessions"""
    session_service = get_session_service()  # Use dependency injection
    
    while True:
        try:
            await asyncio.sleep(config.sessions.cleanup_interval_minutes * 60)
            logger.info("🧹 Running session cleanup task...")
            
            cleaned = session_service.cleanup_expired_sessions(
                timeout_hours=config.sessions.session_timeout_hours
            )
            
            if cleaned > 0:
                logger.info(f"✅ Cleaned up {cleaned} expired sessions")
            
            # Log stats using clean service
            stats = session_service.get_stats()
            logger.info(f"📊 Session stats: Active={stats.active_sessions}, Total={stats.total_sessions_created}")
            
            # Log skill usage
            if stats.active_skills > 0:
                logger.info(f"🤖 Active skills: {stats.skills_in_use}")
            
        except Exception as e:
            logger.error(f"❌ Session cleanup task error: {e}")


# SECURITY: Background task for security monitoring (unchanged for Phase 1)
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
    """Application lifespan with Phase 1 clean architecture"""
    logger.info("=" * 70)
    logger.info("🚀 June Orchestrator v7.2-PHASE1 - Clean Architecture Refactor")
    logger.info("=" * 70)
    
    # Initialize services through dependency injection
    session_service = get_session_service()
    
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
    
    # Voice configuration (kept for compatibility)
    voices = get_available_voices()
    default_voice_ref = resolve_voice_reference(None, None)
    logger.info(f"🎭 Voice Configuration:")
    logger.info(f"  Available Voices: {len(voices)}")
    logger.info(f"  Voice Registry: {list(voices.keys())[:3]}...")
    logger.info(f"  Default Voice: {default_voice_ref}")
    
    # PHASE 1: Clean session configuration
    logger.info(f"📝 Session Configuration (Phase 1 Clean):")
    logger.info(f"  Max History: {config.sessions.max_history_messages} messages")
    logger.info(f"  Session Timeout: {config.sessions.session_timeout_hours} hours")
    logger.info(f"  Service: Clean SessionService initialized")
    
    # SECURITY configuration
    logger.info(f"🔒 Security Configuration:")
    logger.info(f"  Rate Limiting: {rate_limiter.ai_calls_per_minute}/min, {rate_limiter.ai_calls_per_hour}/hour")
    logger.info(f"  Daily Cost Limit: ${call_tracker.max_daily_cost}")
    logger.info(f"  Daily Call Limit: {call_tracker.max_daily_calls}")
    logger.info(f"  Circuit Breaker: {'Enabled' if not circuit_breaker.is_open else 'OPEN'}")
    
    # Skill system (unchanged for Phase 1)
    skills = skill_service.list_skills()
    logger.info(f"🎭 Skill System:")
    logger.info(f"  Available Skills: {list(skills.keys())}")
    logger.info(f"  Ready Skills: ['mockingbird']")
    logger.info(f"  Voice Profiles: {len(voice_profile_service.profiles)}")
    
    # PHASE 1 indicators
    logger.info("✨ PHASE 1 REFACTOR COMPLETE:")
    logger.info("  ✅ Clean Domain Models")
    logger.info("  ✅ Dependency Injection")
    logger.info("  ✅ SessionService Extracted")
    logger.info("  ✅ External Client Abstractions")
    logger.info("  🚧 Phase 2: Route Handlers (Next)")
    
    logger.info("=" * 70)
    
    # Start background tasks
    cleanup_task = asyncio.create_task(cleanup_sessions_task())
    security_task = asyncio.create_task(security_monitoring_task())
    logger.info("✅ Background tasks started (cleanup + security monitoring)")
    
    yield
    
    # Cleanup on shutdown
    cleanup_task.cancel()
    security_task.cancel()
    session_service = get_session_service()
    logger.info("🛑 Shutting down...")
    logger.info(f"📊 Final session stats: {session_service.get_stats()}")
    logger.info(f"🎭 Final voice profile stats: {voice_profile_service.get_stats()}")
    logger.info(f"💰 Final cost stats: {call_tracker.get_stats()}")


app = FastAPI(
    title="June Orchestrator",
    version="7.2.0-PHASE1",
    description="AI Voice Assistant Orchestrator - Phase 1 Clean Architecture Refactor",
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

# Register routes (unchanged for Phase 1 - will be refactored in Phase 2)
app.include_router(webhooks_router, tags=["Webhooks & Skills & Security"])
app.include_router(voices_router, tags=["Voice Management"])
app.include_router(livekit_router, tags=["LiveKit"])


@app.get("/", response_model=ServiceInfoResponse)
async def root():
    """Root endpoint using clean architecture - Phase 1"""
    # Use clean service
    session_service = get_session_service()
    stats = session_service.get_stats()
    
    # Legacy services (will be refactored in Phase 2)
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
        "version": "7.2.0-PHASE1",
        "description": "AI Voice Assistant Orchestrator - Phase 1 Clean Architecture Refactor",
        "features": [
            "✅ PHASE 1: Clean Domain Models",
            "✅ PHASE 1: Dependency Injection",
            "✅ PHASE 1: SessionService Extracted",
            "✅ PHASE 1: External Client Abstractions",
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
            "🎭 NEW: Voice Registry & Emotion Controls",
            "🚧 NEXT: Phase 2 Route Handlers"
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
            },
            "phase1_features": {
                "clean_domain_models": True,
                "dependency_injection": True,
                "session_service_extracted": True,
                "external_client_abstractions": True
            }
        }
    }


@app.get("/healthz")
async def healthz():
    """Health check using clean architecture - Phase 1"""
    # Use clean service
    session_service = get_session_service()
    stats = session_service.get_stats()
    
    # Legacy services (unchanged for Phase 1)
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
        "version": "7.2.0-PHASE1",
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
            "emotion_controls": True,
            # Phase 1 indicators
            "phase1_clean_architecture": True,
            "dependency_injection": True,
            "session_service_extracted": True
        }
    }