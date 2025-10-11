"""
LiveKit Room Manager
Handles room creation, token generation, and room lifecycle
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from livekit import api

from .config import livekit_config

logger = logging.getLogger(__name__)


class LiveKitManager:
    """Manages LiveKit rooms and tokens"""
    
    def __init__(self):
        if not livekit_config.is_configured:
            logger.warning("LiveKit not configured - missing API credentials")
            self.api = None
            return
        
        self.api = api.LiveKitAPI(
            url=livekit_config.url,
            api_key=livekit_config.api_key,
            api_secret=livekit_config.api_secret
        )
        
        logger.info(f"LiveKit manager initialized: {livekit_config.url}")
    
    async def create_token(
        self,
        user_id: str,
        room_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create access token for user to join room
        
        Args:
            user_id: Unique user identifier
            room_name: Room name (auto-generated if None)
            metadata: Optional user metadata
            
        Returns:
            JWT token string
        """
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        room_name = room_name or f"{livekit_config.default_room_name}-{user_id}"
        
        # Create token with permissions
        token = api.AccessToken(
            api_key=livekit_config.api_key,
            api_secret=livekit_config.api_secret
        )
        
        token.with_identity(user_id)
        token.with_name(metadata.get("name", user_id) if metadata else user_id)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True
        ))
        
        # Set metadata
        if metadata:
            token.with_metadata(str(metadata))
        
        # Set expiry
        token.with_ttl(timedelta(seconds=livekit_config.token_ttl))
        
        jwt_token = token.to_jwt()
        
        logger.info(f"Created token for user {user_id} in room {room_name}")
        
        return jwt_token
    
    async def create_room(
        self,
        room_name: str,
        empty_timeout: Optional[int] = None,
        max_participants: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a new LiveKit room
        
        Args:
            room_name: Unique room name
            empty_timeout: Seconds before empty room is deleted
            max_participants: Maximum participants allowed
            
        Returns:
            Room information
        """
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        try:
            room = await self.api.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=empty_timeout or livekit_config.empty_timeout,
                    max_participants=max_participants or livekit_config.max_participants
                )
            )
            
            logger.info(f"Created room: {room_name}")
            
            return {
                "name": room.name,
                "sid": room.sid,
                "created_at": room.creation_time,
                "num_participants": room.num_participants
            }
            
        except Exception as e:
            logger.error(f"Failed to create room {room_name}: {e}")
            raise
    
    async def get_room(self, room_name: str) -> Optional[Dict[str, Any]]:
        """Get room information"""
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        try:
            room = await self.api.room.get_room(room_name)
            
            return {
                "name": room.name,
                "sid": room.sid,
                "num_participants": room.num_participants,
                "created_at": room.creation_time
            }
            
        except Exception as e:
            logger.warning(f"Room {room_name} not found: {e}")
            return None
    
    async def list_rooms(self) -> list:
        """List all active rooms"""
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        try:
            rooms = await self.api.room.list_rooms()
            
            return [
                {
                    "name": room.name,
                    "sid": room.sid,
                    "num_participants": room.num_participants
                }
                for room in rooms
            ]
            
        except Exception as e:
            logger.error(f"Failed to list rooms: {e}")
            return []
    
    async def delete_room(self, room_name: str) -> bool:
        """Delete a room"""
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        try:
            await self.api.room.delete_room(room_name)
            logger.info(f"Deleted room: {room_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete room {room_name}: {e}")
            return False
    
    async def get_participants(self, room_name: str) -> list:
        """List participants in a room"""
        if not self.api:
            raise RuntimeError("LiveKit not configured")
        
        try:
            participants = await self.api.room.list_participants(room_name)
            
            return [
                {
                    "identity": p.identity,
                    "name": p.name,
                    "sid": p.sid,
                    "joined_at": p.joined_at
                }
                for p in participants
            ]
            
        except Exception as e:
            logger.error(f"Failed to list participants in {room_name}: {e}")
            return []


# Global manager instance
livekit_manager = LiveKitManager()