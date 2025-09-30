"""
June Dark OSINT Framework - Orchestrator
Main API and coordination service
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio
import logging

from config import settings
from models.database import DatabaseManager
from models.queue import QueueManager
from models.storage import StorageManager
from api import health, crawl, alerts, system
from utils.scheduler import TaskScheduler

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global managers
db_manager: Optional[DatabaseManager] = None
queue_manager: Optional[QueueManager] = None
storage_manager: Optional[StorageManager] = None
scheduler: Optional[TaskScheduler] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager"""
    global db_manager, queue_manager, storage_manager, scheduler
    
    logger.info("Starting June Dark Orchestrator...")
    
    try:
        # Initialize database connections
        logger.info("Connecting to databases...")
        db_manager = DatabaseManager(
            postgres_dsn=settings.POSTGRES_DSN,
            neo4j_uri=settings.NEO4J_URI,
            neo4j_user=settings.NEO4J_USER,
            neo4j_password=settings.NEO4J_PASSWORD,
            elastic_url=settings.ELASTIC_URL,
            redis_url=settings.REDIS_URL
        )
        await db_manager.connect_all()
        
        # Initialize queue manager
        logger.info("Connecting to RabbitMQ...")
        queue_manager = QueueManager(rabbit_url=settings.RABBIT_URL)
        await queue_manager.connect()
        
        # Initialize storage manager
        logger.info("Connecting to MinIO...")
        storage_manager = StorageManager(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        await storage_manager.initialize()
        
        # Initialize task scheduler
        logger.info("Starting task scheduler...")
        scheduler = TaskScheduler(db_manager, queue_manager)
        scheduler.start()
        
        # Store managers in app state
        app.state.db = db_manager
        app.state.queue = queue_manager
        app.state.storage = storage_manager
        app.state.scheduler = scheduler
        
        logger.info("✓ June Dark Orchestrator started successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to start Orchestrator: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down June Dark Orchestrator...")
        
        if scheduler:
            scheduler.stop()
        
        if queue_manager:
            await queue_manager.close()
        
        if db_manager:
            await db_manager.close_all()
        
        logger.info("✓ Orchestrator shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="June Dark OSINT Orchestrator",
    description="Control plane API for OSINT framework",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(crawl.router, prefix="/api/v1/crawl", tags=["Crawling"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "June Dark OSINT Orchestrator",
        "version": "1.0.0",
        "status": "operational",
        "mode": settings.MODE,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/info")
async def service_info():
    """Service information"""
    return {
        "service": "orchestrator",
        "version": "1.0.0",
        "mode": settings.MODE,
        "features": {
            "crawling": True,
            "enrichment": True,
            "vision": True,
            "alerts": True,
            "opencti": settings.FEATURE_OPENCTI,
            "dark_web": settings.FEATURE_DARK_WEB,
            "social_api": settings.FEATURE_SOCIAL_API
        },
        "configuration": {
            "postgres": bool(settings.POSTGRES_DSN),
            "neo4j": bool(settings.NEO4J_URI),
            "elasticsearch": bool(settings.ELASTIC_URL),
            "redis": bool(settings.REDIS_URL),
            "rabbitmq": bool(settings.RABBIT_URL),
            "minio": bool(settings.MINIO_ENDPOINT)
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        workers=2,
        log_level=settings.LOG_LEVEL.lower()
    )