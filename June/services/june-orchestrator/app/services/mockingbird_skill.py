"""
Mockingbird Voice Cloning Skill
MCP-compatible skill for real-time voice cloning with LiveKit audio capture

FLOW:
1. User: "June, enable mockingbird"
2. June: "I'll clone your voice! Please speak naturally for about 6-10 seconds..."
3. Mockingbird spawns invisible LiveKit client
4. Records user's audio directly from room
5. Processes voice clone
6. June responds in cloned voice: "Got it! I'm now speaking with your voice."
"""
import asyncio
import logging
import tempfile
import time
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import soundfile as sf
import numpy as np
from livekit import rtc, api

logger = logging.getLogger(__name__)


class MockingbirdState(str, Enum):
    """Mockingbird skill states"""
    INACTIVE = "inactive"
    AWAITING_SAMPLE = "awaiting_voice_sample"
    CAPTURING = "capturing_audio"
    CLONING = "cloning_voice"
    ACTIVE = "active"
    ERROR = "error"


@dataclass
class VoiceSample:
    """Captured voice sample data"""
    audio_data: bytes
    sample_rate: int
    duration_seconds: float
    timestamp: datetime


class MockingbirdSkill:
    """
    Voice cloning skill - allows June to speak in user's voice
    
    MCP-compatible: Can be called by LLM via tool use
    Self-contained: Spawns own LiveKit client to record audio
    """
    
    def __init__(
        self, 
        tts_service,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str
    ):
        self.tts = tts_service
        self.livekit_url = livekit_url
        self.livekit_api_key = livekit_api_key
        self.livekit_api_secret = livekit_api_secret
        
        # Session state tracking
        self.sessions: Dict[str, Dict[str, Any]] = {}
        
        # Voice sample requirements
        self.min_sample_duration = 6.0  # seconds
        self.max_sample_duration = 12.0  # seconds
        self.target_sample_duration = 8.0  # ideal
        
        # Recording tasks
        self.recording_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info("✅ Mockingbird voice cloning skill initialized with LiveKit")
    
    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Get or create session state"""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "state": MockingbirdState.INACTIVE,
                "cloned_voice_id": None,
                "room_name": None,
                "capture_start_time": None,
                "activated_at": None
            }
        return self.sessions[session_id]
    
    def is_active(self, session_id: str) -> bool:
        """Check if mockingbird is active for this session"""
        state = self.get_session_state(session_id)
        return state["state"] in [
            MockingbirdState.AWAITING_SAMPLE,
            MockingbirdState.CAPTURING,
            MockingbirdState.CLONING,
            MockingbirdState.ACTIVE
        ]
    
    def get_current_voice_id(self, session_id: str) -> str:
        """Get the voice ID to use for this session"""
        state = self.get_session_state(session_id)
        
        if state["state"] == MockingbirdState.ACTIVE and state["cloned_voice_id"]:
            return state["cloned_voice_id"]
        
        return "default"
    
    async def enable(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """
        Enable mockingbird - start voice cloning flow
        
        Returns:
            Response with instructions for user
        """
        state = self.get_session_state(session_id)
        
        # Check if already active
        if state["state"] != MockingbirdState.INACTIVE:
            return {
                "status": "already_active",
                "message": "Mockingbird is already active or in progress",
                "current_state": state["state"]
            }
        
        # Start capture flow
        state["state"] = MockingbirdState.AWAITING_SAMPLE
        state["activated_at"] = datetime.utcnow()
        state["room_name"] = room_name
        
        logger.info(f"🎤 Mockingbird enabled for session {session_id[:8]}...")
        
        # Start background recording task
        task = asyncio.create_task(
            self._record_audio_from_room(session_id, room_name)
        )
        self.recording_tasks[session_id] = task
        
        return {
            "status": "awaiting_sample",
            "message": (
                "I'll clone your voice! Please speak naturally for about 6 to 10 seconds. "
                "You can say anything - tell me about your day, count to 20, or recite a poem. "
                "Just keep talking naturally, and I'll let you know when I have enough!"
            ),
            "instruction": "speak_naturally",
            "target_duration": self.target_sample_duration,
            "min_duration": self.min_sample_duration
        }
    
    async def _record_audio_from_room(self, session_id: str, room_name: str):
        """
        Spawn temporary LiveKit client to record audio
        This runs in background - invisible to user
        """
        state = self.get_session_state(session_id)
        
        try:
            # Generate token for recording bot
            token = api.AccessToken(self.livekit_api_key, self.livekit_api_secret)
            token.with_identity(f"mockingbird_{session_id[:8]}")
            token.with_name("Mockingbird Recorder")
            token.with_grants(api.VideoGrants(
                room_join=True,
                room=room_name,
                can_subscribe=True,
                can_publish=False  # Read-only participant
            ))
            
            jwt = token.to_jwt()
            
            logger.info(f"🎙️ Spawning LiveKit recorder for room '{room_name}'")
            
            # Connect to room
            room = rtc.Room()
            audio_buffer: List[bytes] = []
            sample_rate = 48000  # LiveKit default
            start_time = None
            recording_started = False
            
            @room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.RemoteTrack,
                publication: rtc.RemoteTrackPublication,
                participant: rtc.RemoteParticipant
            ):
                """Called when we subscribe to a track"""
                nonlocal start_time, recording_started
                
                # Only record audio from the USER (not bots or TTS)
                if (track.kind == rtc.TrackKind.KIND_AUDIO and 
                    participant.identity == session_id):
                    
                    logger.info(f"🎤 Recording audio from {participant.identity}")
                    state["state"] = MockingbirdState.CAPTURING
                    start_time = time.time()
                    recording_started = True
                    
                    # Create audio stream and start capturing
                    asyncio.create_task(
                        self._capture_audio_frames(
                            track,
                            audio_buffer,
                            session_id,
                            start_time,
                            room
                        )
                    )
            
            # Connect to room
            await room.connect(
                self.livekit_url, 
                jwt,
                options=rtc.RoomOptions(auto_subscribe=True)
            )
            logger.info(f"✅ Connected to room '{room_name}' as recorder")
            
            # Wait for recording to complete or timeout (max 20 seconds)
            timeout = 20
            elapsed = 0
            while elapsed < timeout:
                await asyncio.sleep(1)
                elapsed += 1
                
                # Check if we got enough audio
                if recording_started and start_time:
                    duration = time.time() - start_time
                    if duration >= self.target_sample_duration:
                        logger.info(f"✅ Target duration reached: {duration:.1f}s")
                        break
            
            # Disconnect
            await room.disconnect()
            logger.info(f"🔌 Disconnected recorder from room")
            
            # Process captured audio
            if audio_buffer and recording_started:
                logger.info(f"📊 Captured {len(audio_buffer)} audio frames")
                await self._process_captured_audio(
                    session_id, 
                    audio_buffer, 
                    sample_rate,
                    room_name
                )
            else:
                logger.error(f"❌ No audio captured from room (started: {recording_started})")
                state["state"] = MockingbirdState.ERROR
                await self._send_error_message(room_name)
                
        except Exception as e:
            logger.error(f"❌ Recording error: {e}", exc_info=True)
            state["state"] = MockingbirdState.ERROR
            await self._send_error_message(room_name)
        finally:
            # Cleanup
            if session_id in self.recording_tasks:
                del self.recording_tasks[session_id]
    
    async def _capture_audio_frames(
    self,
    track: rtc.RemoteTrack,
    buffer: List[bytes],
    session_id: str,
    start_time: float,
    room: rtc.Room
):
    """Capture audio frames from track"""
    try:
        # Create audio stream from track
        audio_stream = rtc.AudioStream(track)
        
        logger.info(f"🎵 Starting audio frame capture...")
        
        async for event in audio_stream:
            # ✅ FIXED: Access frame through event.frame
            frame = event.frame
            
            # Convert frame to bytes and add to buffer
            # frame.data is a numpy array
            audio_data = frame.data.tobytes()
            buffer.append(audio_data)
            
            # Check if we have enough
            elapsed = time.time() - start_time
            
            if elapsed >= self.max_sample_duration:
                logger.info(f"✅ Max duration reached: {elapsed:.1f}s - stopping capture")
                break
        
        logger.info(f"🎵 Audio capture completed: {len(buffer)} frames")
        
    except Exception as e:
        logger.error(f"❌ Frame capture error: {e}", exc_info=True)

    
    async def _process_captured_audio(
        self, 
        session_id: str, 
        audio_buffer: List[bytes],
        sample_rate: int,
        room_name: str
    ):
        """Process the captured audio and clone voice"""
        state = self.get_session_state(session_id)
        state["state"] = MockingbirdState.CLONING
        
        try:
            # Send "processing" message
            await self.tts.publish_to_room(
                room_name=room_name,
                text="Thank you! Processing your voice sample now...",
                voice_id="default",
                streaming=True
            )
            
            # Combine audio frames
            combined_audio = b''.join(audio_buffer)
            
            logger.info(f"📊 Combined audio size: {len(combined_audio)} bytes")
            
            # Convert to numpy array (LiveKit uses float32)
            # Each sample is 4 bytes (float32)
            audio_array = np.frombuffer(combined_audio, dtype=np.float32)
            
            duration = len(audio_array) / sample_rate
            logger.info(f"🎵 Processing {duration:.1f}s of audio at {sample_rate} Hz")
            
            if duration < self.min_sample_duration:
                raise ValueError(f"Audio too short: {duration:.1f}s (min: {self.min_sample_duration}s)")
            
            # Save to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                sf.write(tmp_path, audio_array, sample_rate)
            
            try:
                # Clone voice
                voice_id = f"mockingbird_{session_id[:8]}_{int(time.time())}"
                voice_name = f"Mockingbird Clone - {session_id[:8]}"
                
                logger.info(f"🔬 Cloning voice as '{voice_id}'...")
                
                result = await self.tts.clone_voice(
                    voice_id=voice_id,
                    voice_name=voice_name,
                    audio_file_path=tmp_path
                )
                
                if result.get("status") == "success":
                    state["state"] = MockingbirdState.ACTIVE
                    state["cloned_voice_id"] = voice_id
                    logger.info(f"✅ Voice cloned successfully: {voice_id}")
                    
                    # Send confirmation in CLONED VOICE
                    await self.tts.publish_to_room(
                        room_name=room_name,
                        text="Got it! I'm now speaking with your voice.",
                        voice_id=voice_id,  # ← Use cloned voice!
                        streaming=True
                    )
                else:
                    raise Exception(f"Voice cloning failed: {result.get('detail', 'Unknown error')}")
                    
            finally:
                # Cleanup temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"❌ Voice cloning error: {e}", exc_info=True)
            state["state"] = MockingbirdState.ERROR
            await self._send_error_message(room_name)
    
    async def _send_error_message(self, room_name: str):
        """Send error message to user"""
        try:
            await self.tts.publish_to_room(
                room_name=room_name,
                text="Sorry, I had trouble cloning your voice. Let's try again later.",
                voice_id="default",
                streaming=True
            )
        except Exception as e:
            logger.error(f"❌ Error sending error message: {e}")
    
    async def disable(self, session_id: str) -> Dict[str, Any]:
        """
        Disable mockingbird - return to default voice
        
        Returns:
            Confirmation response
        """
        state = self.get_session_state(session_id)
        
        if state["state"] == MockingbirdState.INACTIVE:
            return {
                "status": "already_inactive",
                "message": "Mockingbird is not active"
            }
        
        # Cancel recording task if active
        if session_id in self.recording_tasks:
            self.recording_tasks[session_id].cancel()
            del self.recording_tasks[session_id]
        
        # Get voice ID before clearing
        voice_id = state.get("cloned_voice_id")
        
        # Reset state
        state["state"] = MockingbirdState.INACTIVE
        state["cloned_voice_id"] = None
        state["room_name"] = None
        state["capture_start_time"] = None
        
        logger.info(f"🔇 Mockingbird disabled for session {session_id[:8]}...")
        
        # Optionally delete cloned voice
        if voice_id and voice_id != "default":
            try:
                await self.tts.delete_voice(voice_id)
                logger.info(f"🗑️ Deleted cloned voice: {voice_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not delete voice {voice_id}: {e}")
        
        return {
            "status": "disabled",
            "message": "Switching back to my default voice.",
            "previous_voice": voice_id
        }
    
    def get_status(self, session_id: str) -> Dict[str, Any]:
        """Get current mockingbird status for session"""
        state = self.get_session_state(session_id)
        
        return {
            "session_id": session_id,
            "state": state["state"],
            "active": self.is_active(session_id),
            "cloned_voice_id": state.get("cloned_voice_id"),
            "current_voice": self.get_current_voice_id(session_id),
            "activated_at": state.get("activated_at").isoformat() if state.get("activated_at") else None
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall skill statistics"""
        active_sessions = sum(
            1 for state in self.sessions.values() 
            if state["state"] != MockingbirdState.INACTIVE
        )
        
        cloned_voices = sum(
            1 for state in self.sessions.values()
            if state.get("cloned_voice_id") is not None
        )
        
        return {
            "skill": "mockingbird",
            "total_sessions": len(self.sessions),
            "active_sessions": active_sessions,
            "cloned_voices": cloned_voices,
            "recording_tasks": len(self.recording_tasks),
            "states": {
                state: sum(1 for s in self.sessions.values() if s["state"] == state)
                for state in MockingbirdState
            }
        }


# ============================================================================
# TOOL DEFINITIONS FOR NEW GOOGLE-GENAI SDK
# ============================================================================

def enable_mockingbird() -> dict:
    """Enable voice cloning mode (Mockingbird). June will clone the user's voice and speak with it.
    
    Use when user asks to 'enable mockingbird', 'clone my voice', 'speak in my voice', or similar requests.
    
    Returns:
        dict: Status and instructions for voice capture
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


def disable_mockingbird() -> dict:
    """Disable voice cloning mode and return to default voice.
    
    Use when user asks to 'disable mockingbird', 'stop using my voice', 'go back to your voice', or similar requests.
    
    Returns:
        dict: Status confirmation
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


def check_mockingbird_status() -> dict:
    """Check if Mockingbird voice cloning is currently active and which voice is being used.
    
    Use when user asks about mockingbird status or which voice is being used.
    
    Returns:
        dict: Current status information
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


# Export functions as tools (new SDK format)
MOCKINGBIRD_TOOLS = [enable_mockingbird, disable_mockingbird, check_mockingbird_status]
