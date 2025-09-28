# app/routers/admin.py - Enhanced with memory monitoring
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import verify_api_key
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["admin"])

@router.get("/healthz")
def health_check():
    """Enhanced health check with memory info"""
    try:
        from app.core.openvoice_engine import get_engine_status, log_memory_usage
        
        status = get_engine_status()
        
        # Log memory usage
        log_memory_usage("Health Check")
        
        return {
            "status": "healthy",
            "service": "june-tts",
            "version": "1.0-optimized",
            "engine": status
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {e}")

@router.get("/v1/voices")
def list_voices():
    """Get available voices with lazy loading support"""
    try:
        from app.core.openvoice_engine import get_available_voices
        
        voices = get_available_voices()
        
        return {
            "status": "success",
            "voices": voices,
            "optimization_note": "Speakers load on first TTS request for better startup performance"
        }
    except Exception as e:
        logger.error(f"Failed to get voices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get voices: {e}")

@router.get("/v1/status")
def get_detailed_status():
    """Get detailed system status"""
    try:
        from app.core.openvoice_engine import get_engine_status
        import torch
        import psutil
        
        engine_status = get_engine_status()
        
        # System info
        system_info = {
            "cpu_count": os.cpu_count(),
            "memory_total_gb": psutil.virtual_memory().total / 1024**3,
            "memory_used_gb": psutil.virtual_memory().used / 1024**3,
            "memory_percent": psutil.virtual_memory().percent
        }
        
        # GPU info
        gpu_info = {}
        if torch.cuda.is_available():
            gpu_info = {
                "cuda_available": True,
                "gpu_count": torch.cuda.device_count(),
                "gpu_name": torch.cuda.get_device_name(0),
                "gpu_memory_allocated_gb": torch.cuda.memory_allocated() / 1024**3,
                "gpu_memory_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3
            }
        else:
            gpu_info = {"cuda_available": False}
        
        return {
            "status": "success",
            "timestamp": str(__import__('datetime').datetime.now()),
            "engine": engine_status,
            "system": system_info,
            "gpu": gpu_info,
            "optimization": {
                "lazy_loading": True,
                "caching_enabled": True,
                "quantization": os.getenv("ENABLE_QUANTIZATION", "true").lower() == "true"
            }
        }
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}")

@router.post("/admin/cache/clear")
def clear_cache_admin(api_key: str = Depends(verify_api_key)):
    """Clear TTS cache (admin only)"""
    try:
        from app.core.openvoice_engine import clear_cache
        
        cache_size_before = len(getattr(clear_cache, '_tts_cache', {}))
        clear_cache()
        
        return {
            "status": "success",
            "message": f"Cache cleared ({cache_size_before} items removed)",
            "timestamp": str(__import__('datetime').datetime.now())
        }
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {e}")

@router.get("/admin/memory")
def get_memory_stats(api_key: str = Depends(verify_api_key)):
    """Get detailed memory statistics (admin only)"""
    try:
        from app.core.openvoice_engine import log_memory_usage
        import torch
        import psutil
        import gc
        
        # Force garbage collection
        gc.collect()
        
        # System memory
        vm = psutil.virtual_memory()
        process = psutil.Process()
        
        memory_stats = {
            "system": {
                "total_gb": vm.total / 1024**3,
                "available_gb": vm.available / 1024**3,
                "used_gb": vm.used / 1024**3,
                "percent": vm.percent
            },
            "process": {
                "rss_gb": process.memory_info().rss / 1024**3,
                "vms_gb": process.memory_info().vms / 1024**3
            }
        }
        
        # GPU memory if available
        if torch.cuda.is_available():
            memory_stats["gpu"] = {
                "allocated_gb": torch.cuda.memory_allocated() / 1024**3,
                "cached_gb": torch.cuda.memory_reserved() / 1024**3,
                "total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3
            }
        
        # Log current state
        log_memory_usage("Admin Memory Check")
        
        return {
            "status": "success",
            "memory": memory_stats,
            "timestamp": str(__import__('datetime').datetime.now())
        }
    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get memory stats: {e}")
