"""
LiveKit Audio Handlers
Processes audio tracks from LiveKit rooms
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable
import numpy as np

from livekit import rtc

from .config import livekit_config

logger = logging.getLogger(__name__)


class AudioHandler:
    """Handles audio track processing from LiveKit"""
    
    def __init__(self):
        self.active_rooms: dict = {}
        self.audio_callback: Optional[Callable] = None
        
        logger.info("AudioHandler initialized")
    
    def set_audio_callback(self, callback: Callable[[str, bytes], Awaitable[None]]):
        """
        Set callback for processed audio
        
        Args:
            callback: async function(user_id, audio_bytes)
        """
        self.audio_callback = callback
        logger.info("Audio callback registered")
    
    async def join_room(
        self,
        url: str,
        token: str,
        room_name: str,
        user_id: str
    ):
        """
        Join a LiveKit room and start processing audio
        
        Args:
            url: LiveKit server URL
            token: Access token
            room_name: Room name
            user_id: User identifier
        """
        try:
            room = rtc.Room()
            
            # Set up event handlers
            @room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.Track,
                publication: rtc.TrackPublication,
                participant: rtc.RemoteParticipant
            ):
                logger.info(f"Track subscribed: {track.kind} from {participant.identity}")
                
                if track.kind == rtc.TrackKind.KIND_AUDIO:
                    # Start processing this audio track
                    asyncio.create_task(
                        self._process_audio_track(track, participant, user_id)
                    )
            
            @room.on("participant_connected")
            def on_participant_connected(participant: rtc.RemoteParticipant):
                logger.info(f"Participant connected: {participant.identity}")
            
            @room.on("participant_disconnected")
            def on_participant_disconnected(participant: rtc.RemoteParticipant):
                logger.info(f"Participant disconnected: {participant.identity}")
            
            # Connect to room
            await room.connect(url, token)
            
            logger.info(f"Joined room {room_name} as {user_id}")
            
            # Store room reference
            self.active_rooms[room_name] = {
                "room": room,
                "user_id": user_id,
                "connected_at": asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Failed to join room {room_name}: {e}")
            raise
    
    async def _process_audio_track(
        self,
        track: rtc.AudioTrack,
        participant: rtc.RemoteParticipant,
        user_id: str
    ):
        """
        Process audio frames from a track
        
        Args:
            track: Audio track
            participant: Remote participant
            user_id: User identifier
        """
        logger.info(f"Starting audio processing for {participant.identity}")
        
        audio_buffer = []
        buffer_duration = 1.0  # 1 second buffer
        
        try:
            async for frame in rtc.AudioStream(track):
                # Convert frame to numpy array
                audio_data = np.frombuffer(
                    frame.data.tobytes(),
                    dtype=np.int16
                )
                
                audio_buffer.append(audio_data)
                
                # Calculate buffered duration
                total_samples = sum(len(arr) for arr in audio_buffer)
                duration = total_samples / livekit_config.sample_rate
                
                # Process buffer when full
                if duration >= buffer_duration:
                    # Concatenate buffer
                    full_audio = np.concatenate(audio_buffer)
                    audio_bytes = full_audio.tobytes()
                    
                    # Clear buffer
                    audio_buffer = []
                    
                    # Send to callback
                    if self.audio_callback:
                        await self.audio_callback(user_id, audio_bytes)
                    else:
                        logger.warning("No audio callback registered")
                
        except Exception as e:
            logger.error(f"Error processing audio track: {e}")
    
    async def leave_room(self, room_name: str):
        """Disconnect from a room"""
        if room_name in self.active_rooms:
            room_info = self.active_rooms[room_name]
            room = room_info["room"]
            
            await room.disconnect()
            del self.active_rooms[room_name]
            
            logger.info(f"Left room {room_name}")
    
    async def cleanup_all(self):
        """Disconnect from all rooms"""
        for room_name in list(self.active_rooms.keys()):
            await self.leave_room(room_name)
        
        logger.info("All rooms cleaned up")


# Global handler instance
audio_handler = AudioHandler()