import os
from typing import Optional

class Config:
    # Port configuration (multi-service)
    PORT: int = int(os.getenv("TTS_PORT", "8000"))
    
    # LiveKit configuration  
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        "ws://livekit-livekit-server.june-services.svc.cluster.local:80"
    )
    LIVEKIT_API_KEY: Optional[str] = os.getenv("LIVEKIT_API_KEY")
    LIVEKIT_API_SECRET: Optional[str] = os.getenv("LIVEKIT_API_SECRET")
    
    # Orchestrator configuration
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    
    # TTS configuration
    TTS_MODEL: str = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
    TTS_CACHE_PATH: str = os.getenv("TTS_CACHE_PATH", "/app/cache")
    TTS_HOME: str = os.getenv("TTS_HOME", "/app/models")
    
    # Room configuration
    ROOM_NAME: str = os.getenv("ROOM_NAME", "ozzu-main")
    
    # Authentication
    BEARER_TOKEN: Optional[str] = os.getenv("BEARER_TOKEN")
    
    # Debug
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

config = Config()