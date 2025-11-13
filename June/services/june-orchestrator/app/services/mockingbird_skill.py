"""
Mockingbird Voice Cloning Skill - WORKING VERSION
Uses LiveKit 0.11.1 event-based API correctly
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
    """Voice cloning skill with LiveKit audio capture"""
    
    def __init__(
        self, 
        tts_service,
        conversation_manager,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str
    ):
        self.tts = tts_service
        self.conversation_manager = conversation_manager
        self.livekit_url = livekit_url
        self.livekit_api_key = livekit_api_key
        self.livekit_api_secret = livekit_api_secret
        
        self.sessions: Dict[str, SessionState] = {}
        self.min_sample_duration = 4.0
        self.max_sample_duration = 15.0
        self.target_sample_duration = 8.0
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
        """Enable mockingbird - start voice cloning flow"""
        state = self.get_session_state(session_id)
        
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
        
        if not self.conversation_manager.is_participant_in_room(session_id, room_name):
            logger.error(f"❌ Session {session_id[:8]}... not found in room {room_name}")
            return {
                "status": "error",
                "tts_message": "I can't find you in the room. Please make sure you're connected.",
                "skip_llm_response": True
            }
        
        participant_info = self.conversation_manager.get_participant_info(session_id)
        if not participant_info:
            logger.error(f"❌ No participant info for session {session_id[:8]}...")
            return {
                "status": "error",
                "tts_message": "I'm having trouble finding your audio. Please try again.",
                "skip_llm_response": True
            }
        
        logger.info(
            f"✅ Participant check passed: {participant_info.identity} "
            f"(audio_available={participant_info.is_publishing_audio})"
        )
        
        state.state = MockingbirdState.AWAITING_SAMPLE
        state.activated_at = datetime.utcnow()
        state.room_name = room_name
        
        logger.info(f"🎤 Mockingbird enabled for session {session_id[:8]}...")
        
        task = asyncio.create_task(
            self._record_audio_from_room(session_id, room_name)
        )
        self.recording_tasks[session_id] = task
        
        return {
            "status": "awaiting_sample",
            "tts_message": (
                "Ready to clone your voice! Please speak naturally for about 8 seconds. "
                "Start speaking now!"
            ),
            "skip_llm_response": True
        }
    
    async def _record_audio_from_room(
        self,
        session_id: str,
        room_name: str
    ) -> Optional[bytes]:
        """Record audio using LiveKit 0.11.1 event-based API"""
        state = self.get_session_state(session_id)
        state.state = MockingbirdState.CAPTURING
        
        room = rtc.Room()
        audio_buffer = []
        audio_stream = None
        recording_complete = asyncio.Event()
        
        try:
            target_identity = self.conversation_manager.get_participant_identity(session_id)
            if not target_identity:
                logger.error(f"❌ Could not find identity for session {session_id}")
                return None
            
            logger.info(f"🎯 Target participant identity: {target_identity}")
            
            jwt = api.AccessToken(self.livekit_api_key, self.livekit_api_secret) \
                .with_identity(f"recorder-{session_id[:8]}") \
                .with_name("Voice Recorder") \
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_subscribe=True,
                    can_publish=False
                )).to_jwt()
            
            logger.info(f"🎤 Spawning LiveKit recorder for room '{room_name}'")
            
            @room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.Track,
                publication: rtc.RemoteTrackPublication,
                participant: rtc.RemoteParticipant
            ):
                nonlocal audio_stream
                
                if participant.identity == target_identity and track.kind == rtc.TrackKind.KIND_AUDIO:
                    logger.info(f"🎤 Audio track subscribed for {target_identity}")
                    audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
                    asyncio.create_task(self._collect_frames(audio_stream, audio_buffer, recording_complete))
            
            await room.connect(
                self.livekit_url,
                jwt,
                options=rtc.RoomOptions(auto_subscribe=True)
            )
            
            logger.info(f"✅ Connected to room '{room_name}' as recorder")
            
            try:
                await asyncio.wait_for(recording_complete.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("⚠️ Recording timeout - using what we have")
            
            if audio_buffer:
                await self._process_captured_audio(
                    session_id=session_id,
                    audio_buffer=audio_buffer,
                    sample_rate=16000,
                    room_name=room_name
                )
            else:
                logger.warning("⚠️ No audio frames captured")
                state.state = MockingbirdState.ERROR
                await self._send_tts(
                    room_name,
                    "Sorry, I couldn't capture any audio. Please try again.",
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
            try:
                await room.disconnect()
            except:
                pass
    
    async def _collect_frames(
        self,
        audio_stream: rtc.AudioStream,
        audio_buffer: List[bytes],
        recording_complete: asyncio.Event
    ):
        """Collect audio frames from stream"""
        try:
            logger.info(f"🎤 Recording audio for {self.target_sample_duration}s...")
            start_time = time.time()
            frame_count = 0
            
            async for event in audio_stream:
                frame = event.frame
                audio_buffer.append(bytes(frame.data))
                frame_count += 1
                
                elapsed = time.time() - start_time
                if elapsed >= self.target_sample_duration:
                    logger.info(f"✅ Recording complete! Collected {frame_count} frames")
                    break
                
                if frame_count % 50 == 0:
                    logger.info(f"📊 Recording... {elapsed:.1f}s / {self.target_sample_duration}s")
            
            recording_complete.set()
            
        except Exception as e:
            logger.error(f"❌ Frame collection error: {e}", exc_info=True)
            recording_complete.set()
    
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
            await self._send_tts(
                room_name, 
                "Thank you! Processing your voice sample now...", 
                "default"
            )
            
            combined_audio = b''.join(audio_buffer)
            audio_array = np.frombuffer(combined_audio, dtype=np.float32)
            duration = len(audio_array) / sample_rate
            
            logger.info(f"🎵 Processing {duration:.1f}s of audio at {sample_rate} Hz")
            
            if duration < self.min_sample_duration:
                raise ValueError(f"Audio too short: {duration:.1f}s (min: {self.min_sample_duration}s)")
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                sf.write(tmp_path, audio_array, sample_rate)
            
            try:
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
                    
                    await self._send_tts(
                        room_name,
                        "Got it! I'm now speaking with your voice.",
                        voice_id
                    )
                else:
                    raise Exception(f"Voice cloning failed: {result.get('detail', 'Unknown error')}")
                    
            finally:
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
        
        if session_id in self.recording_tasks:
            self.recording_tasks[session_id].cancel()
            del self.recording_tasks[session_id]
        
        voice_id = state.cloned_voice_id
        
        state.state = MockingbirdState.INACTIVE
        state.cloned_voice_id = None
        state.room_name = None
        
        logger.info(f"🔇 Mockingbird disabled for session {session_id[:8]}...")
        
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