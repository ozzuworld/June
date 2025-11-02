"""LiveKit service client - Phase 1 refactor"""
import logging
from typing import Dict, Any, Optional
from livekit import api

logger = logging.getLogger(__name__)


class LiveKitClient:
    """Clean LiveKit service client"""
    
    def __init__(self, api_key: str, api_secret: str, ws_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = ws_url
        
        logger.info(f"✅ LiveKitClient initialized with URL: {ws_url}")
    
    async def generate_access_token(
        self, 
        room_name: str, 
        participant_name: str, 
        permissions: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate LiveKit access token"""
        try:
            token = api.AccessToken(self.api_key, self.api_secret)
            token.with_identity(participant_name)
            token.with_name(participant_name)
            
            # Set permissions
            permissions = permissions or {
                "can_publish": True,
                "can_subscribe": True,
                "can_publish_data": True,
                "hidden": False,
                "recorder": False
            }
            
            grants = api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=permissions.get("can_publish", True),
                can_subscribe=permissions.get("can_subscribe", True),
                can_publish_data=permissions.get("can_publish_data", True),
                hidden=permissions.get("hidden", False),
                recorder=permissions.get("recorder", False)
            )
            
            token.with_grants(grants)
            
            access_token = token.to_jwt()
            logger.info(f"✅ Generated access token for {participant_name} in room {room_name}")
            return access_token
            
        except Exception as e:
            logger.error(f"Failed to generate LiveKit token: {e}")
            raise
    
    def get_connection_info(self) -> Dict[str, str]:
        """Get LiveKit connection information"""
        return {
            "livekit_url": self.ws_url,
            "api_key": self.api_key  # Don't expose secret
        }