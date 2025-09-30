"""
Health check endpoints
"""

from fastapi import APIRouter, Request
from datetime import datetime
from typing import Dict, Any

router = APIRouter()


@router.get("")
async def health_check(request: Request) -> Dict[str, Any]:
    """
    Comprehensive health check for all services
    """
    db_manager = request.app.state.db
    queue_manager = request.app.state.queue
    
    # Check database health
    db_health = await db_manager.health_check()
    
    # Check queue connection
    queue_health = queue_manager.connected
    
    # Determine overall status
    all_healthy = all([
        db_health.get("postgres"),
        db_health.get("neo4j"),
        db_health.get("elasticsearch"),
        db_health.get("redis"),
        queue_health
    ])
    
    status = "healthy" if all_healthy else "degraded"
    
    return {
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "postgres": "up" if db_health.get("postgres") else "down",
            "neo4j": "up" if db_health.get("neo4j") else "down",
            "elasticsearch": "up" if db_health.get("elasticsearch") else "down",
            "redis": "up" if db_health.get("redis") else "down",
            "rabbitmq": "up" if queue_health else "down"
        }
    }


@router.get("/ready")
async def readiness_check(request: Request) -> Dict[str, Any]:
    """
    Kubernetes readiness probe
    """
    db_manager = request.app.state.db
    
    # Check if database connections are ready
    db_health = await db_manager.health_check()
    
    is_ready = all([
        db_health.get("postgres"),
        db_health.get("elasticsearch")
    ])
    
    return {
        "ready": is_ready,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/live")
async def liveness_check() -> Dict[str, Any]:
    """
    Kubernetes liveness probe
    """
    return {
        "alive": True,
        "timestamp": datetime.utcnow().isoformat()
    }