import os
from typing import Optional

class Config:
    # Port configuration (multi-service)
    PORT: int = int(os.getenv("STT_PORT", "8001"))
    
    # LiveKit configuration - Updated for Tailscale/standalone deployment
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        "ws://june-livekit:7880"  # Updated for Tailscale network
    )
    LIVEKIT_API_KEY: Optional[str] = os.getenv("LIVEKIT_API_KEY")
    LIVEKIT_API_SECRET: Optional[str] = os.getenv("LIVEKIT_API_SECRET")
    
    # Orchestrator configuration - Updated for Tailscale network
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator:8080"  # Updated for Tailscale network
    )
    
    # Whisper configuration
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cuda")
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Room configuration
    ROOM_NAME: str = os.getenv("ROOM_NAME", "ozzu-main")
    
    # Authentication
    BEARER_TOKEN: Optional[str] = os.getenv("BEARER_TOKEN")
    
    # Debug
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

config = Config()