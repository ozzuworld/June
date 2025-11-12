"""
Mockingbird Voice Cloning Skill - PRODUCTION VERSION
All fixes applied based on architecture analysis
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
class SessionState:
    """State for a single mockingbird session"""
    state: MockingbirdState = MockingbirdState.INACTIVE
    cloned_voice_id: Optional[str] = None
    room_name: Optional[str] = None
    activated_at: Optional[datetime] = None
    
    def is_busy(self) -> bool:
        """Check if mockingbird is in a state where it should ignore transcripts"""
        return self.state in [
            MockingbirdState.AWAITING_SAMPLE,
            MockingbirdState.CAPTURING,
            MockingbirdState.CLONING
        ]
    
    def is_active(self) -> bool:
        """Check if mockingbird is active (voice cloned and ready)"""
        return self.state == MockingbirdState.ACTIVE


class MockingbirdSkill:
    """
    Voice cloning skill with self-contained LiveKit audio capture
    
    FIXED ISSUES:
    - Event-driven LiveKit (no remote_participants access)
    - Proper state checking to prevent transcript processing during recording
    - Resource cleanup on errors
    - Better timeout handling
    - Comprehensive logging
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
        self.sessions: Dict[str, SessionState] = {}
        
        # Voice sample requirements
        self.min_sample_duration = 4.0  # seconds
        self.max_sample_duration = 15.0  # seconds
        self.target_sample_duration = 8.0  # ideal
        
        # Recording tasks
        self.recording_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info("✅ Mockingbird voice cloning skill initialized")
    
    def get_session_state(self, session_id: str) -> SessionState:
        """Get or create session state"""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState()
        return self.sessions[session_id]
    
    def get_current_voice_id(self, session_id: str) -> str:
        """Get the voice ID to use for this session"""
        state = self.get_session_state(session_id)
        
        if state.is_active() and state.cloned_voice_id:
            return state.cloned_voice_id
        
        return "default"
    
    async def enable(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """
        Enable mockingbird - start voice cloning flow
        
        Returns instruction message that will be sent via TTS
        """
        state = self.get_session_state(session_id)
        
        # Check if already active
        if state.state != MockingbirdState.INACTIVE:
            logger.warning(f"⚠️ Mockingbird already in state: {state.state}")
            
            if state.state == MockingbirdState.ACTIVE:
                return {
                    "status": "already_active",
                    "tts_message": "Mockingbird is already active. I'm using your cloned voice right now.",
                    "skip_llm_response": True
                }
            else:
                return {
                    "status": "in_progress",
                    "tts_message": "Mockingbird is already in progress. Please wait.",
                    "skip_llm_response": True
                }
        
        # Start capture flow
        state.state = MockingbirdState.AWAITING_SAMPLE
        state.activated_at = datetime.utcnow()
        state.room_name = room_name
        
        logger.info(f"🎤 Mockingbird enabled for session {session_id[:8]}...")
        
        # Start background recording task
        task = asyncio.create_task(
            self._record_audio_from_room(session_id, room_name)
        )
        self.recording_tasks[session_id] = task
        
        # Return message that will be sent via TTS
        return {
            "status": "awaiting_sample",
            "tts_message": (
                "I'll clone your voice! Please speak naturally for about 6 to 10 seconds. "
                "You can say anything - tell me about your day, count to 20, or recite a poem. "
                "Just keep talking naturally, and I'll let you know when I have enough!"
            ),
            "skip_llm_response": True
        }
    
    async def _record_audio_from_room(self, session_id: str, room_name: str):
        """
        Connect to LiveKit room and record user audio
        
        ✅ FIXED: Event-driven only, no remote_participants access
        """
        state = self.get_session_state(session_id)
        room: Optional[rtc.Room] = None
        
        try:
            # Generate token for recording bot
            token = api.AccessToken(self.livekit_api_key, self.livekit_api_secret)
            token.with_identity(f"mockingbird_{session_id[:8]}")
            token.with_name("Mockingbird Recorder")
            token.with_grants(api.VideoGrants(
                room_join=True,
                room=room_name,
                can_subscribe=True,
                can_publish=False,
                hidden=True  # Hide from participant list
            ))
            
            jwt = token.to_jwt()
            
            logger.info(f"🎙️ Spawning LiveKit recorder for room '{room_name}'")
            
            # Audio capture state
            audio_buffer: List[bytes] = []
            sample_rate = 48000
            capture_start_time: Optional[float] = None
            audio_track_found = False
            
            # Create room
            room = rtc.Room()
            
            # ✅ Event handler for participant connection
            @room.on("participant_connected")
            def on_participant_connected(participant: rtc.RemoteParticipant):
                """Called when a participant joins"""
                logger.info(f"👤 Participant connected: {participant.identity}")
                
                # If it's our target, subscribe to their tracks
                if participant.identity == session_id:
                    logger.info(f"🎯 Target participant joined! Subscribing to audio...")
                    asyncio.create_task(self._subscribe_to_participant(participant))
            
            # ✅ Event handler for track subscription
            @room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.Track,
                publication: rtc.RemoteTrackPublication,
                participant: rtc.RemoteParticipant
            ):
                nonlocal audio_track_found, capture_start_time
                
                # Only record audio from the target user
                is_target_audio = (
                    track.kind == rtc.TrackKind.KIND_AUDIO and 
                    participant.identity == session_id
                )
                
                if is_target_audio:
                    logger.info(f"🎤 Recording audio from {participant.identity}")
                    audio_track_found = True
                    state.state = MockingbirdState.CAPTURING
                    capture_start_time = time.time()
                    
                    # Start capturing frames
                    asyncio.create_task(
                        self._capture_frames(track, audio_buffer, session_id)
                    )
                else:
                    logger.debug(f"⏭️ Ignoring track from {participant.identity}")
            
            # Connect to room
            await room.connect(
                self.livekit_url,
                jwt,
                options=rtc.RoomOptions(auto_subscribe=False)  # Manual subscription
            )
            
            logger.info(f"✅ Connected to room '{room_name}' as recorder")
            
            # Wait a moment for room to stabilize
            await asyncio.sleep(1.0)
            
            # ✅ Use event system, wait for participants
            logger.info(f"🔍 Room connected, waiting for participants via events...")
            
            # Wait for audio capture (with timeout)
            timeout = 20  # seconds
            elapsed = 0
            
            while elapsed < timeout:
                await asyncio.sleep(0.5)
                elapsed += 0.5
                
                # Check if we have enough audio
                if capture_start_time:
                    duration = time.time() - capture_start_time
                    
                    if duration >= self.target_sample_duration:
                        logger.info(f"✅ Target duration reached: {duration:.1f}s")
                        break
                
                # Warn if no audio found after 5 seconds
                if elapsed >= 5 and not audio_track_found:
                    logger.warning(f"⚠️ No user audio track found after 5s")
            
            # Disconnect
            if room:
                await room.disconnect()
            logger.info(f"🔌 Disconnected recorder from room")
            
            # Process captured audio
            if audio_buffer and capture_start_time:
                duration = time.time() - capture_start_time
                logger.info(f"📊 Captured {len(audio_buffer)} frames ({duration:.1f}s)")
                await self._process_captured_audio(
                    session_id, audio_buffer, sample_rate, room_name
                )
            else:
                logger.error(f"❌ No audio captured")
                state.state = MockingbirdState.ERROR
                await self._send_tts(
                    room_name, 
                    "Sorry, I had trouble capturing your voice. Let's try again later.", 
                    "default"
                )
                
        except Exception as e:
            logger.error(f"❌ Recording error: {e}", exc_info=True)
            state.state = MockingbirdState.ERROR
            await self._send_tts(
                room_name, 
                "Sorry, I had trouble recording. Let's try again later.", 
                "default"
            )
        finally:
            # Cleanup
            if session_id in self.recording_tasks:
                del self.recording_tasks[session_id]
            
            if room and room.connection_state != rtc.ConnectionState.CONN_DISCONNECTED:
                try:
                    await room.disconnect()
                except:
                    pass
    
    async def _subscribe_to_participant(self, participant: rtc.RemoteParticipant):
        """Subscribe to audio tracks from a participant"""
        try:
            # Wait a moment for tracks to be available
            await asyncio.sleep(0.3)
            
            # Get track publications - convert to dict for safe iteration
            publications = dict(participant.track_publications)
            
            logger.info(f"🔍 Participant has {len(publications)} track publications")
            
            for track_sid, publication in publications.items():
                if publication.kind == rtc.TrackKind.KIND_AUDIO:
                    logger.info(f"🔔 Subscribing to audio track: {track_sid}")
                    publication.set_subscribed(True)
                    
        except Exception as e:
            logger.error(f"❌ Error subscribing to participant: {e}")
    
    async def _capture_frames(
        self,
        track: rtc.Track,
        buffer: List[bytes],
        session_id: str
    ):
        """Capture audio frames from track"""
        try:
            audio_stream = rtc.AudioStream(track)
            logger.info(f"🎵 Starting frame capture...")
            
            frame_count = 0
            start_time = time.time()
            
            async for event in audio_stream:
                frame = event.frame
                
                # Convert frame data to bytes
                audio_data = frame.data.tobytes()
                buffer.append(audio_data)
                frame_count += 1
                
                # Log progress every 100 frames (~1 second)
                if frame_count % 100 == 0:
                    elapsed = time.time() - start_time
                    logger.debug(f"📊 Captured {frame_count} frames ({elapsed:.1f}s)")
                
                # Stop if we have enough
                elapsed = time.time() - start_time
                if elapsed >= self.max_sample_duration:
                    logger.info(f"✅ Max duration reached: {elapsed:.1f}s")
                    break
            
            logger.info(f"🎵 Capture complete: {frame_count} frames in {time.time() - start_time:.1f}s")
            
        except Exception as e:
            logger.error(f"❌ Frame capture error: {e}", exc_info=True)
    
    async def _process_captured_audio(
        self,
        session_id: str,
        audio_buffer: List[bytes],
        sample_rate: int,
        room_name: str
    ):
        """Process captured audio and clone voice"""
        state = self.get_session_state(session_id)
        state.state = MockingbirdState.CLONING
        
        try:
            # Send processing message
            await self._send_tts(
                room_name, 
                "Thank you! Processing your voice sample now...", 
                "default"
            )
            
            # Combine audio frames
            combined_audio = b''.join(audio_buffer)
            
            # Convert to numpy array (LiveKit uses float32)
            audio_array = np.frombuffer(combined_audio, dtype=np.float32)
            
            # Calculate duration
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
                voice_name = f"Cloned Voice - {session_id[:8]}"
                
                logger.info(f"🔬 Cloning voice as '{voice_id}'...")
                
                result = await self.tts.clone_voice(
                    voice_id=voice_id,
                    voice_name=voice_name,
                    audio_file_path=tmp_path
                )
                
                if result.get("status") == "success":
                    state.state = MockingbirdState.ACTIVE
                    state.cloned_voice_id = voice_id
                    logger.info(f"✅ Voice cloned successfully: {voice_id}")
                    
                    # Send confirmation in CLONED VOICE
                    await self._send_tts(
                        room_name,
                        "Got it! I'm now speaking with your voice.",
                        voice_id
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
            logger.error(f"❌ Voice processing error: {e}", exc_info=True)
            state.state = MockingbirdState.ERROR
            await self._send_tts(
                room_name, 
                "Sorry, I had trouble processing your voice. Let's try again later.", 
                "default"
            )
    
    async def _send_tts(self, room_name: str, text: str, voice_id: str):
        """Helper to send TTS message"""
        try:
            await self.tts.publish_to_room(
                room_name=room_name,
                text=text,
                voice_id=voice_id,
                streaming=True
            )
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")
    
    async def disable(self, session_id: str) -> Dict[str, Any]:
        """Disable mockingbird and return to default voice"""
        state = self.get_session_state(session_id)
        
        if state.state == MockingbirdState.INACTIVE:
            return {
                "status": "already_inactive",
                "tts_message": "Mockingbird is not active.",
                "skip_llm_response": True
            }
        
        # Cancel recording task if active
        if session_id in self.recording_tasks:
            self.recording_tasks[session_id].cancel()
            del self.recording_tasks[session_id]
        
        # Get voice ID before clearing
        voice_id = state.cloned_voice_id
        
        # Reset state
        state.state = MockingbirdState.INACTIVE
        state.cloned_voice_id = None
        state.room_name = None
        
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
            "tts_message": "Switching back to my default voice.",
            "skip_llm_response": True
        }
    
    def check_status(self, session_id: str) -> Dict[str, Any]:
        """Get current mockingbird status"""
        state = self.get_session_state(session_id)
        
        if state.is_active():
            status_msg = f"Mockingbird is active! I'm using your cloned voice."
        elif state.is_busy():
            status_msg = f"Mockingbird is {state.state}. Please wait..."
        else:
            status_msg = "Mockingbird is not active. I'm using my default voice."
        
        return {
            "status": state.state,
            "tts_message": status_msg,
            "skip_llm_response": True,
            "active": state.is_active(),
            "voice_id": state.cloned_voice_id or "default"
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall skill statistics"""
        active_count = sum(1 for s in self.sessions.values() if s.is_active())
        busy_count = sum(1 for s in self.sessions.values() if s.is_busy())
        
        return {
            "skill": "mockingbird",
            "total_sessions": len(self.sessions),
            "active_sessions": active_count,
            "busy_sessions": busy_count,
            "recording_tasks": len(self.recording_tasks)
        }


# ============================================================================
# TOOL DECLARATIONS FOR GEMINI
# ============================================================================

def enable_mockingbird() -> dict:
    """Enable voice cloning mode (Mockingbird). June will clone the user's voice.
    
    Use when user asks to:
    - 'enable mockingbird'
    - 'clone my voice'
    - 'speak in my voice'
    - 'use my voice'
    - 'turn on mockingbird'
    - 'activate mockingbird'
    
    This will record a voice sample and clone the user's voice for June to use.
    """
    pass


def disable_mockingbird() -> dict:
    """Disable voice cloning and return to default voice.
    
    Use when user asks to:
    - 'disable mockingbird'
    - 'use your voice'
    - 'stop using my voice'
    - 'turn off mockingbird'
    - 'use your normal voice'
    - 'deactivate mockingbird'
    """
    pass


def check_mockingbird_status() -> dict:
    """Check if Mockingbird is currently active and which voice is being used.
    
    Use when user asks:
    - 'is mockingbird on'
    - 'what voice are you using'
    - 'are you using my voice'
    - 'mockingbird status'
    - 'is voice cloning active'
    """
    pass


MOCKINGBIRD_TOOLS = [enable_mockingbird, disable_mockingbird, check_mockingbird_status]