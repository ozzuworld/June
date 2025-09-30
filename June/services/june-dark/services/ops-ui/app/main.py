"""
June Dark Ops UI - Monitoring Dashboard
"""

import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from elasticsearch import AsyncElasticsearch
from redis.asyncio import Redis
import aio_pika

from config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="June Dark Ops UI",
    description="Operations and monitoring dashboard",
    version="1.0.0"
)

# Templates
templates = Jinja2Templates(directory="templates")

# Global clients
es_client: AsyncElasticsearch = None
redis_client: Redis = None
rabbit_connection: aio_pika.RobustConnection = None


@app.on_event("startup")
async def startup():
    """Initialize connections on startup"""
    global es_client, redis_client
    
    logger.info("Starting Ops UI...")
    
    try:
        # Elasticsearch
        es_client = AsyncElasticsearch([settings.ELASTIC_URL])
        await es_client.ping()
        logger.info("✓ Elasticsearch connected")
        
        # Redis
        redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("✓ Redis connected")
        
        logger.info("✓ Ops UI started successfully")
    
    except Exception as e:
        logger.error(f"Failed to start Ops UI: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if es_client:
        await es_client.close()
    if redis_client:
        await redis_client.close()
    logger.info("✓ Ops UI shutdown complete")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "June Dark Operations Dashboard"
    })


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ops-ui",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/stats")
async def get_stats() -> Dict[str, Any]:
    """Get system statistics"""
    try:
        # Get stats from orchestrator
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.ORCHESTRATOR_URL}/api/v1/system/stats",
                timeout=10.0
            )
            orchestrator_stats = response.json() if response.status_code == 200 else {}
        
        # Get Elasticsearch stats
        es_stats = {}
        try:
            indices = await es_client.cat.indices(format="json")
            es_stats = {
                "total_indices": len(indices),
                "total_docs": sum(int(idx.get("docs.count", 0)) for idx in indices if idx.get("docs.count")),
                "total_size": sum(int(idx.get("store.size", "0").replace("kb", "000").replace("mb", "000000").replace("gb", "000000000")) for idx in indices)
            }
        except Exception as e:
            logger.error(f"Error getting ES stats: {e}")
        
        # Get queue stats from orchestrator
        queue_stats = orchestrator_stats.get("queues", {})
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "orchestrator": orchestrator_stats.get("database", {}),
            "elasticsearch": es_stats,
            "queues": queue_stats
        }
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {"error": str(e)}


@app.get("/api/crawl/stats")
async def get_crawl_stats():
    """Get crawling statistics"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.ORCHESTRATOR_URL}/api/v1/crawl/stats",
                timeout=10.0
            )
            return response.json() if response.status_code == 200 else {"error": "Failed to fetch stats"}
    except Exception as e:
        logger.error(f"Error getting crawl stats: {e}")
        return {"error": str(e)}


@app.get("/api/alerts/summary")
async def get_alerts_summary():
    """Get alerts summary"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.ORCHESTRATOR_URL}/api/v1/alerts/stats/summary",
                timeout=10.0
            )
            return response.json() if response.status_code == 200 else {"error": "Failed to fetch alerts"}
    except Exception as e:
        logger.error(f"Error getting alert stats: {e}")
        return {"error": str(e)}


@app.get("/api/queue/status")
async def get_queue_status():
    """Get queue status"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.ORCHESTRATOR_URL}/api/v1/system/stats",
                timeout=10.0
            )
            data = response.json() if response.status_code == 200 else {}
            return data.get("queues", {})
    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        return {"error": str(e)}


@app.post("/api/mode/{mode}")
async def switch_mode(mode: str):
    """Switch operational mode"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.ORCHESTRATOR_URL}/api/v1/system/mode/{mode}",
                timeout=10.0
            )
            return response.json() if response.status_code == 200 else {"error": "Failed to switch mode"}
    except Exception as e:
        logger.error(f"Error switching mode: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)