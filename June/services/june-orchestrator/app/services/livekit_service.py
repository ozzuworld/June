"""LiveKit service - simplified to focus on token generation only"""
import logging
from typing import Dict, Optional
from datetime import timedelta

from livekit import api

from ..config import config

logger = logging.getLogger(__name__)


class LiveKitService:
    """LiveKit service focused on authentication and essential operations only
    
    Note: LiveKit automatically handles:
    - Room creation when first participant joins
    - Room cleanup when last participant leaves  
    - Participant state management
    - Media track lifecycle
    
    This service only handles what requires server-side logic:
    - JWT token generation
    - Administrative operations when explicitly needed
    """
    
    def generate_access_token(
        self, 
        room_name: str, 
        participant_name: str,
        permissions: Optional[Dict] = None
    ) -> str:
        """Generate JWT access token for a participant
        
        LiveKit will automatically:
        - Create the room when this participant connects (if it doesn't exist)
        - Handle all participant state management
        - Clean up when participants leave
        """
        try:
            # Default permissions - LiveKit handles enforcement
            default_permissions = {
                "can_publish": True,
                "can_subscribe": True,
                "can_publish_data": True,
                "hidden": False,
                "recorder": False
            }
            
            if permissions:
                default_permissions.update(permissions)
            
            # Create access token
            token = api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret
            )
            
            # Set token claims
            token.with_identity(participant_name)
            token.with_name(participant_name)
            
            # Room permissions - LiveKit enforces these automatically
            grant = api.VideoGrant(
                room_join=True,
                room=room_name,
                can_publish=default_permissions["can_publish"],
                can_subscribe=default_permissions["can_subscribe"],
                can_publish_data=default_permissions["can_publish_data"],
                hidden=default_permissions["hidden"],
                recorder=default_permissions["recorder"]
            )
            token.with_grants(grant)
            
            # Set expiration (24 hours from now)
            token.with_ttl(timedelta(hours=24))
            
            access_token = token.to_jwt()
            
            logger.info(f"✅ Generated access token for {participant_name} in room {room_name}")
            logger.info(f"📝 LiveKit will auto-create room '{room_name}' when participant connects")
            return access_token
            
        except Exception as e:
            logger.error(f"Failed to generate access token for {participant_name}: {e}")
            raise
    
    def get_connection_info(self) -> Dict[str, str]:
        """Get LiveKit connection information for clients"""
        return {
            "livekit_url": config.livekit.ws_url,
            "api_key": config.livekit.api_key
        }


# Global instance
livekit_service = LiveKitService()