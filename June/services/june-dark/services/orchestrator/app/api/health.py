"""
Health check endpoints
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def health_check(request: Request):
    """Basic health check"""
    try:
        # Check database connections
        db_status = {}
        if hasattr(request.app.state, 'db') and request.app.state.db:
            db_manager = request.app.state.db
            db_status = {
                "postgres": db_manager.pg_pool is not None,
                "neo4j": db_manager.neo4j_driver is not None,
                "elasticsearch": db_manager.es_client is not None,
                "redis": db_manager.redis_client is not None
            }
        
        # Check queue manager
        queue_status = {}
        if hasattr(request.app.state, 'queue') and request.app.state.queue:
            queue_manager = request.app.state.queue
            queue_status = {
                "rabbitmq": queue_manager.connection is not None
            }
        
        # Check storage manager
        storage_status = {}
        if hasattr(request.app.state, 'storage') and request.app.state.storage:
            storage_manager = request.app.state.storage
            storage_status = {
                "minio": storage_manager.client is not None
            }
        
        return JSONResponse({
            "status": "healthy",
            "service": "orchestrator",
            "version": "1.0.0",
            "databases": db_status,
            "queue": queue_status,
            "storage": storage_status
        })
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            {
                "status": "unhealthy", 
                "error": str(e),
                "service": "orchestrator"
            }, 
            status_code=503
        )

@router.get("/detailed")
async def detailed_health_check(request: Request):
    """Detailed health check with connection tests"""
    health_status = {
        "status": "healthy",
        "service": "orchestrator",
        "checks": {}
    }
    
    try:
        # Test database connections
        if hasattr(request.app.state, 'db') and request.app.state.db:
            db_manager = request.app.state.db
            
            # PostgreSQL check
            if db_manager.pg_pool:
                try:
                    async with db_manager.pg_pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
                    health_status["checks"]["postgres"] = {"status": "healthy", "connection": "active"}
                except Exception as e:
                    health_status["checks"]["postgres"] = {"status": "unhealthy", "error": str(e)}
            else:
                health_status["checks"]["postgres"] = {"status": "not_configured"}
            
            # Redis check
            if db_manager.redis_client:
                try:
                    await db_manager.redis_client.ping()
                    health_status["checks"]["redis"] = {"status": "healthy", "connection": "active"}
                except Exception as e:
                    health_status["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
            else:
                health_status["checks"]["redis"] = {"status": "not_configured"}
        
        # Overall status
        unhealthy_services = [k for k, v in health_status["checks"].items() if v.get("status") == "unhealthy"]
        if unhealthy_services:
            health_status["status"] = "degraded"
            health_status["unhealthy_services"] = unhealthy_services
        
        return JSONResponse(health_status)
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return JSONResponse(
            {
                "status": "error",
                "error": str(e),
                "service": "orchestrator"
            },
            status_code=500
        )
