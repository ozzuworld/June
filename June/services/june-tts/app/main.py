import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lifespan context manager for optimized startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan with optimized startup"""
    logger.info("🚀 Starting June TTS API with optimizations...")
    
    # Startup
    try:
        from app.core.openvoice_engine import warmup_models, log_memory_usage
        
        # Log initial memory state
        log_memory_usage("Startup")
        
        # Optimized warmup (lazy loading)
        start_time = time.time()
        warmup_models()
        warmup_time = time.time() - start_time
        
        logger.info(f"✅ TTS models initialized in {warmup_time:.2f}s")
        log_memory_usage("After Warmup")
        
    except Exception as e:
        logger.warning(f"⚠️ Warmup skipped: {e}")
    
    yield  # Application runs here
    
    # Shutdown
    try:
        from app.core.openvoice_engine import clear_cache
        clear_cache()
        logger.info("🧹 Cleanup completed")
    except Exception as e:
        logger.warning(f"⚠️ Cleanup warning: {e}")

# Create FastAPI app with lifespan
app = FastAPI(
    title="June TTS API", 
    version="1.0",
    lifespan=lifespan
)

# Add middleware for optimization
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Performance monitoring middleware
@app.middleware("http")
async def performance_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Log slow requests
    if process_time > 2.0:
        logger.warning(f"Slow request: {request.url.path} took {process_time:.2f}s")
    
    response.headers["X-Process-Time"] = str(process_time)
    return response

# ----- CORS -----
origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
origins = [o.strip() for o in origins_env.split(",") if o.strip()]
allow_all = "*" in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Routers -----
try:
    from app.routers.standard_tts import router as standard_tts_router
    app.include_router(standard_tts_router)
    logger.info("✅ Standard TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ standard_tts router load warning: {e}")

try:
    from app.routers.tts import router as tts_router
    app.include_router(tts_router)
    logger.info("✅ TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ tts router load warning: {e}")

try:
    from app.routers.clone import router as clone_router
    app.include_router(clone_router)
    logger.info("✅ Clone router loaded")
except Exception as e:
    logger.warning(f"⚠️ clone router load warning: {e}")

try:
    from app.routers.admin import router as admin_router
    app.include_router(admin_router)
    logger.info("✅ Admin router loaded")
except Exception as e:
    logger.warning(f"⚠️ admin router load warning: {e}")

# ----- Root -----
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "June TTS API (Optimized)",
        "version": "1.0",
        "features": {
            "lazy_loading": True,
            "caching": True,
            "memory_optimization": True,
            "quantization": os.getenv("ENABLE_QUANTIZATION", "true").lower() == "true"
        },
        "endpoints": {
            "standard_tts": "/v1/tts",
            "voice_cloning": "/tts/generate or /clone/voice",
            "health_check": "/healthz",
            "voices": "/v1/voices",
            "status": "/v1/status",
            "cache_clear": "/admin/cache/clear"
        }
    }

# Cache management endpoint
@app.delete("/admin/cache/clear")
async def clear_cache_endpoint():
    """Clear TTS cache"""
    try:
        from app.core.openvoice_engine import clear_cache, log_memory_usage
        
        log_memory_usage("Before Cache Clear")
        clear_cache()
        log_memory_usage("After Cache Clear")
        
        return {"status": "success", "message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return {"status": "error", "message": str(e)}
