"""
Mockingbird Voice Cloning Skill
MCP-compatible skill for real-time voice cloning

FLOW:
1. User: "June, enable mockingbird"
2. June: "I'll clone your voice! Please speak naturally for about 6-10 seconds..."
3. [Captures user audio]
4. [Clones voice, switches to it]
5. June: "Got it! I'm now speaking with your voice." (in user's voice)
6. User: "June, disable mockingbird"
7. June: "Switching back to my default voice" (back to default)
"""
import asyncio
import logging
import tempfile
import time
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import soundfile as sf
import numpy as np

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
    """
    
    def __init__(self, tts_service):
        self.tts = tts_service
        
        # Session state tracking
        self.sessions: Dict[str, Dict[str, Any]] = {}
        
        # Voice sample requirements
        self.min_sample_duration = 6.0  # seconds
        self.max_sample_duration = 12.0  # seconds
        self.target_sample_duration = 8.0  # ideal
        
        # Audio capture buffer
        self.audio_buffers: Dict[str, list] = {}
        
        logger.info("✅ Mockingbird voice cloning skill initialized")
    
    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Get or create session state"""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "state": MockingbirdState.INACTIVE,
                "cloned_voice_id": None,
                "capture_start_time": None,
                "sample_count": 0,
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
    
    async def enable(self, session_id: str, user_id: str) -> Dict[str, Any]:
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
        state["sample_count"] = 0
        
        # Initialize audio buffer
        self.audio_buffers[session_id] = []
        
        logger.info(f"🎤 Mockingbird enabled for session {session_id[:8]}...")
        
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
    
    async def capture_audio_chunk(
        self, 
        session_id: str, 
        audio_data: bytes,
        sample_rate: int = 16000
    ) -> Dict[str, Any]:
        """
        Capture audio chunk during voice sampling
        
        Args:
            session_id: Session identifier
            audio_data: Audio data chunk
            sample_rate: Sample rate of audio
            
        Returns:
            Status update
        """
        state = self.get_session_state(session_id)
        
        # Only capture if awaiting or capturing
        if state["state"] not in [MockingbirdState.AWAITING_SAMPLE, MockingbirdState.CAPTURING]:
            return {"status": "not_capturing"}
        
        # First chunk - start capture timer
        if state["state"] == MockingbirdState.AWAITING_SAMPLE:
            state["state"] = MockingbirdState.CAPTURING
            state["capture_start_time"] = time.time()
            logger.info(f"🎙️ Started capturing voice sample for {session_id[:8]}...")
        
        # Add to buffer
        if session_id not in self.audio_buffers:
            self.audio_buffers[session_id] = []
        
        self.audio_buffers[session_id].append(audio_data)
        state["sample_count"] += 1
        
        # Calculate current duration
        total_bytes = sum(len(chunk) for chunk in self.audio_buffers[session_id])
        # Assume 16-bit audio (2 bytes per sample)
        total_samples = total_bytes // 2
        duration = total_samples / sample_rate
        
        logger.debug(f"📊 Captured {duration:.1f}s of audio (target: {self.target_sample_duration}s)")
        
        # Check if we have enough
        if duration >= self.min_sample_duration:
            # Enough audio - process it
            logger.info(f"✅ Sufficient audio captured ({duration:.1f}s)")
            return await self._process_voice_sample(session_id, sample_rate)
        
        return {
            "status": "capturing",
            "duration": round(duration, 1),
            "target": self.target_sample_duration,
            "progress": min(duration / self.target_sample_duration, 1.0)
        }
    
    async def process_transcript_chunk(
        self,
        session_id: str,
        text: str,
        audio_data: Optional[bytes] = None,
        sample_rate: int = 16000
    ) -> Dict[str, Any]:
        """
        Process transcript during voice capture
        This is called from the main STT webhook
        
        Args:
            session_id: Session ID
            text: Transcribed text
            audio_data: Raw audio if available
            sample_rate: Audio sample rate
            
        Returns:
            Processing result
        """
        state = self.get_session_state(session_id)
        
        # If capturing, add audio to buffer
        if state["state"] in [MockingbirdState.AWAITING_SAMPLE, MockingbirdState.CAPTURING]:
            if audio_data:
                return await self.capture_audio_chunk(session_id, audio_data, sample_rate)
            
            # No audio data - estimate from text
            # Rough estimate: ~3 chars per second of speech
            estimated_duration = len(text) / 3.0
            
            if state["state"] == MockingbirdState.AWAITING_SAMPLE:
                state["state"] = MockingbirdState.CAPTURING
                state["capture_start_time"] = time.time()
            
            elapsed = time.time() - state["capture_start_time"]
            
            if elapsed >= self.min_sample_duration:
                return {
                    "status": "ready_to_clone",
                    "message": "Thank you! Processing your voice sample now..."
                }
        
        return {"status": "not_applicable"}
    
    async def _process_voice_sample(
        self, 
        session_id: str, 
        sample_rate: int
    ) -> Dict[str, Any]:
        """
        Process captured voice sample and create clone
        
        Args:
            session_id: Session ID
            sample_rate: Sample rate
            
        Returns:
            Cloning result
        """
        state = self.get_session_state(session_id)
        state["state"] = MockingbirdState.CLONING
        
        try:
            # Combine audio chunks
            audio_chunks = self.audio_buffers.get(session_id, [])
            if not audio_chunks:
                raise ValueError("No audio data captured")
            
            combined_audio = b''.join(audio_chunks)
            
            # Convert to numpy array (assume 16-bit PCM)
            audio_array = np.frombuffer(combined_audio, dtype=np.int16)
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            duration = len(audio_float) / sample_rate
            logger.info(f"🎵 Processing {duration:.1f}s of audio at {sample_rate} Hz")
            
            # Save to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                sf.write(tmp_path, audio_float, sample_rate)
            
            try:
                # Create unique voice ID for this session
                voice_id = f"mockingbird_{session_id[:8]}_{int(time.time())}"
                voice_name = f"Mockingbird Clone - {session_id[:8]}"
                
                logger.info(f"🔬 Cloning voice as '{voice_id}'...")
                
                # Call TTS voice cloning endpoint
                result = await self.tts.clone_voice(
                    voice_id=voice_id,
                    voice_name=voice_name,
                    audio_file_path=tmp_path
                )
                
                if result.get("status") == "success":
                    # Success! Update state
                    state["state"] = MockingbirdState.ACTIVE
                    state["cloned_voice_id"] = voice_id
                    
                    # Clear buffer
                    self.audio_buffers[session_id] = []
                    
                    logger.info(f"✅ Voice cloned successfully: {voice_id}")
                    
                    return {
                        "status": "success",
                        "voice_id": voice_id,
                        "message": "Got it! I'm now speaking with your voice.",
                        "duration": round(duration, 1),
                        "cloning_result": result
                    }
                else:
                    raise Exception(f"Voice cloning failed: {result.get('detail', 'Unknown error')}")
                    
            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"❌ Voice cloning error: {e}", exc_info=True)
            state["state"] = MockingbirdState.ERROR
            
            return {
                "status": "error",
                "error": str(e),
                "message": "Sorry, I had trouble cloning your voice. Let's try again."
            }
    
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
        
        # Get voice ID before clearing
        voice_id = state.get("cloned_voice_id")
        
        # Reset state
        state["state"] = MockingbirdState.INACTIVE
        state["cloned_voice_id"] = None
        state["capture_start_time"] = None
        
        # Clear buffer
        if session_id in self.audio_buffers:
            del self.audio_buffers[session_id]
        
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
            "states": {
                state: sum(1 for s in self.sessions.values() if s["state"] == state)
                for state in MockingbirdState
            }
        }


# ============================================================================
# TOOL DEFINITIONS FOR NEW GOOGLE-GENAI SDK
# ============================================================================

def enable_mockingbird(confirmation: str = "") -> dict:
    """Enable voice cloning mode (Mockingbird). June will clone the user's voice and speak with it.
    
    Use when user asks to 'enable mockingbird', 'clone my voice', 'speak in my voice', or similar requests.
    
    Args:
        confirmation: Confirmation message to user about starting voice cloning
    
    Returns:
        Status and instructions for voice capture
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


def disable_mockingbird(confirmation: str = "") -> dict:
    """Disable voice cloning mode and return to default voice.
    
    Use when user asks to 'disable mockingbird', 'stop using my voice', 'go back to your voice', or similar requests.
    
    Args:
        confirmation: Confirmation message to user about returning to default voice
    
    Returns:
        Status confirmation
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


def check_mockingbird_status() -> dict:
    """Check if Mockingbird voice cloning is currently active and which voice is being used.
    
    Use when user asks about mockingbird status or which voice is being used.
    
    Returns:
        Current status information
    """
    pass  # Implementation handled by SimpleVoiceAssistant._execute_tool


# Export functions as tools (new SDK format)
MOCKINGBIRD_TOOLS = [enable_mockingbird, disable_mockingbird, check_mockingbird_status]
