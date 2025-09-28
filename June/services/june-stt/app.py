# June/services/june-stt/app.py - Add these monitoring endpoints for external deployment

import platform
import psutil
import socket
from datetime import datetime, timezone
from typing import Dict, Any

from orchestrator_client import get_orchestrator_client
from shared.auth import test_auth_connectivity

# Add these endpoints to your FastAPI app

@app.get("/healthz")
async def health_check():
    """Basic health check for load balancers"""
    model_status = "ready" if whisper_service.model else "loading"
    
    return {
        "status": "healthy" if whisper_service.model else "starting",
        "service": "june-stt",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "model_status": model_status
    }

@app.get("/v1/status")
async def get_detailed_status():
    """Detailed service status for orchestrator and monitoring"""
    model_status = "ready" if whisper_service.model else "loading"
    
    # Get system information
    try:
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage('/')
        cpu_percent = psutil.cpu_percent(interval=1)
    except:
        memory_info = disk_info = None
        cpu_percent = 0
    
    status = {
        "service": {
            "name": "june-stt",
            "version": "2.0.0",
            "status": "healthy" if whisper_service.model else "starting",
            "deployment": "external",
            "started_at": startup_time.isoformat() if 'startup_time' in globals() else None,
            "uptime_seconds": (datetime.utcnow() - startup_time).total_seconds() if 'startup_time' in globals() else 0
        },
        
        "features": {
            "transcription": whisper_service.model is not None,
            "real_time_streaming": False,  # Add if you implement this
            "multi_language": True,
            "translation": True,
            "speaker_diarization": False,  # Add if you implement this
            "confidence_scores": True,
            "timestamps": True
        },
        
        "model": {
            "name": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "status": model_status,
            "loaded_at": whisper_service.model_load_time.isoformat() if hasattr(whisper_service, 'model_load_time') else None
        },
        
        "endpoints": {
            "transcribe": "/v1/transcribe",
            "transcript": "/v1/transcripts/{id}",
            "status": "/v1/status",
            "health": "/healthz",
            "capabilities": "/v1/capabilities",
            "connectivity": "/v1/connectivity"
        },
        
        "configuration": {
            "max_file_size_mb": int(os.getenv("MAX_FILE_SIZE_MB", "25")),
            "max_duration_minutes": int(os.getenv("MAX_DURATION_MINUTES", "30")),
            "max_concurrent": config.MAX_CONCURRENT_TRANSCRIPTIONS if hasattr(config, 'MAX_CONCURRENT_TRANSCRIPTIONS') else 3,
            "retention_hours": config.TRANSCRIPT_RETENTION_HOURS,
            "external_url": os.getenv("EXTERNAL_STT_URL", "not_configured")
        },
        
        "authentication": {
            "provider": "keycloak",
            "realm": os.getenv("KEYCLOAK_REALM", "allsafe"),
            "client_id": os.getenv("KEYCLOAK_CLIENT_ID", "june-stt"),
            "keycloak_url": os.getenv("KEYCLOAK_URL", "not_configured")
        }
    }
    
    # Add system resources if available
    if memory_info and disk_info:
        status["system"] = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory_info.total / (1024**3), 2),
                "available_gb": round(memory_info.available / (1024**3), 2),
                "used_percent": memory_info.percent
            },
            "disk": {
                "total_gb": round(disk_info.total / (1024**3), 2),
                "free_gb": round(disk_info.free / (1024**3), 2),
                "used_percent": round((disk_info.used / disk_info.total) * 100, 1)
            }
        }
    
    return status

@app.get("/v1/capabilities")
async def get_capabilities():
    """Get STT service capabilities for service discovery"""
    return {
        "service_type": "speech_to_text",
        "api_version": "v1",
        "supported_formats": ["wav", "mp3", "m4a", "flac", "ogg", "webm"],
        "supported_languages": [
            "en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko", 
            "ar", "hi", "tr", "pl", "nl", "sv", "da", "no", "fi"
        ],
        "max_file_size_mb": int(os.getenv("MAX_FILE_SIZE_MB", "25")),
        "max_duration_minutes": int(os.getenv("MAX_DURATION_MINUTES", "30")),
        "features": {
            "language_detection": True,
            "automatic_language_detection": True,
            "translation_to_english": True,
            "confidence_scores": True,
            "word_timestamps": True,
            "speaker_diarization": False,
            "real_time_streaming": False,
            "batch_processing": True,
            "webhook_notifications": True
        },
        "authentication": {
            "required": True,
            "methods": ["bearer_token"],
            "scopes": ["stt:transcribe", "stt:read"]
        },
        "rate_limits": {
            "requests_per_minute": int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "100")),
            "concurrent_requests": int(os.getenv("MAX_CONCURRENT_TRANSCRIPTIONS", "3"))
        }
    }

@app.get("/v1/connectivity")
async def test_connectivity():
    """Test connectivity to external services"""
    results = {}
    
    # Test Keycloak connectivity
    auth_result = await test_auth_connectivity()
    results["keycloak"] = auth_result
    
    # Test orchestrator connectivity
    orchestrator_client = get_orchestrator_client()
    orchestrator_result = await orchestrator_client.test_connectivity()
    results["orchestrator"] = orchestrator_result
    
    # Test external URL accessibility (if configured)
    external_url = os.getenv("EXTERNAL_STT_URL")
    if external_url:
        try:
            # Parse URL to get host and port for testing
            from urllib.parse import urlparse
            parsed = urlparse(external_url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            # Test if our external URL is reachable (basic connectivity test)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()
            
            results["external_url"] = {
                "url": external_url,
                "reachable": result == 0,
                "host": host,
                "port": port
            }
        except Exception as e:
            results["external_url"] = {
                "url": external_url,
                "reachable": False,
                "error": str(e)
            }
    
    # Overall connectivity status
    overall_status = "healthy"
    if not auth_result.get("auth_service") == "healthy":
        overall_status = "degraded"
    if not orchestrator_result.get("reachable", False):
        overall_status = "degraded"
    
    return {
        "overall_status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "services": results
    }

# Add startup tracking
startup_time = datetime.utcnow()

@app.on_event("startup")
async def startup_event():
    """Enhanced startup event with external service verification"""
    global startup_time
    startup_time = datetime.utcnow()
    
    logger.info("🚀 Starting June STT Service v2.0.0 (External Deployment)")
    
    # Initialize Whisper model
    await whisper_service.initialize()
    
    # Test external service connectivity
    logger.info("🔗 Testing external service connectivity...")
    
    # Test Keycloak
    try:
        auth_result = await test_auth_connectivity()
        if auth_result.get("auth_service") == "healthy":
            logger.info("✅ Keycloak connectivity: OK")
        else:
            logger.warning(f"⚠️ Keycloak connectivity: {auth_result}")
    except Exception as e:
        logger.error(f"❌ Keycloak connectivity test failed: {e}")
    
    # Test Orchestrator
    try:
        orchestrator_client = get_orchestrator_client()
        orch_result = await orchestrator_client.test_connectivity()
        if orch_result.get("reachable", False):
            logger.info("✅ Orchestrator connectivity: OK")
        else:
            logger.warning(f"⚠️ Orchestrator connectivity: {orch_result}")
    except Exception as e:
        logger.error(f"❌ Orchestrator connectivity test failed: {e}")
    
    # Start background cleanup task
    asyncio.create_task(periodic_cleanup())
    
    # Log configuration
    external_url = os.getenv("EXTERNAL_STT_URL", "not_configured")
    logger.info(f"📡 External STT URL: {external_url}")
    logger.info(f"🔐 Keycloak realm: {os.getenv('KEYCLOAK_REALM', 'not_configured')}")
    logger.info(f"🎯 Orchestrator URL: {os.getenv('ORCHESTRATOR_URL', 'not_configured')}")
    
    logger.info("✅ June STT Service startup complete")

# Add metrics endpoint (optional, for monitoring)
@app.get("/metrics")
async def get_metrics():
    """Prometheus-style metrics for monitoring"""
    if not os.getenv("METRICS_ENABLED", "true").lower() == "true":
        raise HTTPException(status_code=404, detail="Metrics disabled")
    
    # Basic metrics
    active_transcriptions = len([t for t in transcript_storage.values() 
                                if t.status == "processing"])
    total_transcriptions = len(transcript_storage)
    
    # System metrics
    try:
        memory_info = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent()
        disk_info = psutil.disk_usage('/')
    except:
        memory_info = disk_info = None
        cpu_percent = 0
    
    uptime = (datetime.utcnow() - startup_time).total_seconds()
    
    metrics = [
        f"# HELP stt_service_uptime_seconds Service uptime in seconds",
        f"# TYPE stt_service_uptime_seconds counter",
        f"stt_service_uptime_seconds {uptime}",
        "",
        f"# HELP stt_transcriptions_total Total number of transcriptions",
        f"# TYPE stt_transcriptions_total counter", 
        f"stt_transcriptions_total {total_transcriptions}",
        "",
        f"# HELP stt_transcriptions_active Currently active transcriptions",
        f"# TYPE stt_transcriptions_active gauge",
        f"stt_transcriptions_active {active_transcriptions}",
        "",
        f"# HELP stt_model_loaded Whether the Whisper model is loaded",
        f"# TYPE stt_model_loaded gauge",
        f"stt_model_loaded {1 if whisper_service.model else 0}",
    ]
    
    if memory_info:
        metrics.extend([
            "",
            f"# HELP stt_memory_usage_percent Memory usage percentage",
            f"# TYPE stt_memory_usage_percent gauge",
            f"stt_memory_usage_percent {memory_info.percent}",
            "",
            f"# HELP stt_cpu_usage_percent CPU usage percentage",
            f"# TYPE stt_cpu_usage_percent gauge", 
            f"stt_cpu_usage_percent {cpu_percent}",
        ])
    
    if disk_info:
        disk_usage_percent = (disk_info.used / disk_info.total) * 100
        metrics.extend([
            "",
            f"# HELP stt_disk_usage_percent Disk usage percentage",
            f"# TYPE stt_disk_usage_percent gauge",
            f"stt_disk_usage_percent {disk_usage_percent:.1f}",
        ])
    
    return "\n".join(metrics)

# Add CORS middleware for external access
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=os.getenv("CORS_ALLOW_METHODS", "GET,POST,PUT,DELETE,OPTIONS").split(","),
    allow_headers=os.getenv("CORS_ALLOW_HEADERS", "*").split(",") if os.getenv("CORS_ALLOW_HEADERS") != "*" else ["*"],
)