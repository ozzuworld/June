"""
LiveKit Configuration
"""
import os
from pydantic import BaseModel
from typing import Optional


class LiveKitConfig(BaseModel):
    """LiveKit service configuration"""
    
    # Connection
    url: str = os.getenv("LIVEKIT_URL", "ws://livekit-server.june-services.svc.cluster.local:7880")
    api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    
    # Room settings
    default_room_name: str = "june-voice-chat"
    auto_create_room: bool = True
    empty_timeout: int = 300  # 5 minutes
    max_participants: int = 10
    
    # Audio settings
    sample_rate: int = 16000  # For STT
    channels: int = 1
    
    # Token expiry
    token_ttl: int = 3600  # 1 hour
    
    @property
    def is_configured(self) -> bool:
        """Check if LiveKit is properly configured"""
        return bool(self.api_key and self.api_secret)


# Global config instance
livekit_config = LiveKitConfig()