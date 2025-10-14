"""LiveKit service for room and session management"""
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

from livekit import api
from livekit.protocol import room as lk_room
from livekit.protocol import models as lk_models

from ..config import config

logger = logging.getLogger(__name__)


class LiveKitService:
    """LiveKit service for managing rooms and participants"""
    
    def __init__(self):
        self.room_service = api.RoomService(
            host=config.livekit.ws_url.replace('ws://', 'http://').replace('wss://', 'https://'),
            api_key=config.livekit.api_key,
            api_secret=config.livekit.api_secret
        )
    
    async def create_room(self, room_name: str, max_participants: int = 10) -> Dict:
        """Create a LiveKit room"""
        try:
            # Create room with configuration
            room_request = lk_room.CreateRoomRequest(
                name=room_name,
                empty_timeout=30 * 60,  # 30 minutes
                max_participants=max_participants,
                metadata="{\"created_by\": \"june-orchestrator\"}"
            )
            
            room = await self.room_service.create_room(room_request)
            
            logger.info(f"✅ Created LiveKit room: {room_name}")
            return {
                "room_name": room.name,
                "room_sid": room.sid,
                "creation_time": room.creation_time,
                "max_participants": room.max_participants,
                "num_participants": room.num_participants
            }
        except Exception as e:
            logger.error(f"Failed to create LiveKit room {room_name}: {e}")
            raise
    
    def generate_access_token(
        self, 
        room_name: str, 
        participant_name: str,
        permissions: Optional[Dict] = None
    ) -> str:
        """Generate access token for a participant"""
        try:
            # Default permissions
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
            
            # Room permissions
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
            return access_token
            
        except Exception as e:
            logger.error(f"Failed to generate access token for {participant_name}: {e}")
            raise
    
    async def get_room_info(self, room_name: str) -> Optional[Dict]:
        """Get room information"""
        try:
            rooms = await self.room_service.list_rooms(lk_room.ListRoomsRequest(
                names=[room_name]
            ))
            
            if not rooms.rooms:
                return None
            
            room = rooms.rooms[0]
            return {
                "room_name": room.name,
                "room_sid": room.sid,
                "creation_time": room.creation_time,
                "max_participants": room.max_participants,
                "num_participants": room.num_participants,
                "metadata": room.metadata
            }
        except Exception as e:
            logger.error(f"Failed to get room info for {room_name}: {e}")
            return None
    
    async def list_participants(self, room_name: str) -> list:
        """List participants in a room"""
        try:
            participants = await self.room_service.list_participants(
                lk_room.ListParticipantsRequest(room=room_name)
            )
            
            return [
                {
                    "identity": p.identity,
                    "name": p.name,
                    "sid": p.sid,
                    "state": p.state,
                    "joined_at": p.joined_at,
                    "metadata": p.metadata
                }
                for p in participants.participants
            ]
        except Exception as e:
            logger.error(f"Failed to list participants for room {room_name}: {e}")
            return []
    
    async def remove_participant(self, room_name: str, participant_identity: str) -> bool:
        """Remove a participant from a room"""
        try:
            await self.room_service.remove_participant(
                lk_room.RemoveParticipantRequest(
                    room=room_name,
                    identity=participant_identity
                )
            )
            logger.info(f"✅ Removed participant {participant_identity} from room {room_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove participant {participant_identity}: {e}")
            return False
    
    async def delete_room(self, room_name: str) -> bool:
        """Delete a room"""
        try:
            await self.room_service.delete_room(
                lk_room.DeleteRoomRequest(room=room_name)
            )
            logger.info(f"✅ Deleted LiveKit room: {room_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete room {room_name}: {e}")
            return False


# Global instance
livekit_service = LiveKitService()