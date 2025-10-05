"""
Optimized configuration for June STT Service
"""
import os
import torch

class Config:
    # Service
    PORT = int(os.getenv("PORT", "8080"))  # Match K8s service
    
    # Faster-Whisper Optimized Configuration
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    
    # OPTIMIZED: Use int8 for better performance as per best practices
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", 
        "int8" if torch.cuda.is_available() else "int8"
    )
    
    # Performance Settings (Optimized from docs)
    WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    
    # Resource Limits (Simplified)
    MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
    
    # Model caching
    WHISPER_CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Orchestrator Integration (Simplified)
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://june-orchestrator:8080")
    STT_SERVICE_TOKEN = os.getenv("STT_SERVICE_TOKEN", "")
    ORCHESTRATOR_ENABLED = os.getenv("ENABLE_ORCHESTRATOR_NOTIFICATIONS", "true").lower() == "true"

config = Config()
