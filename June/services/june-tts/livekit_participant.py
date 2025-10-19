# June/services/june-tts/livekit_participant.py
"""
TTS Service as LiveKit Room Participant
Joins room, publishes audio responses when triggered by orchestrator
"""
import asyncio
import logging
import os
import tempfile
from typing import Optional
from livekit import rtc, api
import numpy as np
from scipy.io import wavfile

from config import config

logger = logging.getLogger(__name__)


class TTSRoomParticipant:
    """TTS service that joins LiveKit room and publishes audio responses"""
    
    def __init__(self, room_name: str = "ozzu-main"):
        self.room_name = room_name
        self.room: Optional[rtc.Room] = None
        self.audio_source: Optional[rtc.AudioSource] = None
        self.is_connected = False
        
    async def connect(self):
        """Connect to LiveKit room as TTS participant"""
        logger.info(f"🔊 TTS joining room: {self.room_name}")
        
        # Generate access token for TTS service
        token = api.AccessToken(
            api_key=config.LIVEKIT_API_KEY,
            api_secret=config.LIVEKIT_API_SECRET
        )
        token.with_identity("june-tts")
        token.with_name("TTS Service")
        token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,      # Can publish audio
                can_subscribe=False,   # Doesn't need to listen
                can_publish_data=True  # Can send data messages
            )
        )
        access_token = token.to_jwt()
        
        # Connect to room
        self.room = rtc.Room()
        await self.room.connect(config.LIVEKIT_WS_URL, access_token)
        self.is_connected = True
        
        # Create audio source for publishing
        self.audio_source = rtc.AudioSource(
            sample_rate=24000,  # Match TTS output
            num_channels=1
        )
        
        # Publish audio track
        track = rtc.LocalAudioTrack.create_audio_track("tts-audio", self.audio_source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        
        await self.room.local_participant.publish_track(track, options)
        
        logger.info(f"✅ TTS connected to room: {self.room_name}")
        logger.info(f"🎙️ TTS audio track published and ready")
        
    async def speak(self, audio_data: bytes, sample_rate: int = 24000):
        """
        Publish audio to the room
        
        Args:
            audio_data: Raw audio bytes (WAV format)
            sample_rate: Audio sample rate
        """
        if not self.is_connected or not self.audio_source:
            logger.error("TTS not connected to room")
            return
            
        try:
            logger.info(f"🔊 Publishing audio to room ({len(audio_data)} bytes)")
            
            # Save audio to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
            
            # Read audio file
            sr, audio_array = wavfile.read(temp_path)
            
            # Convert to float32 and normalize
            if audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32) / 32768.0
            
            # Ensure mono
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)
            
            # Resample if needed
            if sr != sample_rate:
                from scipy import signal
                num_samples = int(len(audio_array) * sample_rate / sr)
                audio_array = signal.resample(audio_array, num_samples)
            
            # Create audio frames and publish
            frame_samples = 480  # 20ms at 24kHz
            for i in range(0, len(audio_array), frame_samples):
                chunk = audio_array[i:i + frame_samples]
                
                # Pad last chunk if needed
                if len(chunk) < frame_samples:
                    chunk = np.pad(chunk, (0, frame_samples - len(chunk)))
                
                # Create audio frame
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=len(chunk)
                )
                
                # Publish frame
                await self.audio_source.capture_frame(frame)
                
                # Small delay to match real-time playback
                await asyncio.sleep(len(chunk) / sample_rate)
            
            logger.info(f"✅ Audio published to room")
            
            # Cleanup
            os.unlink(temp_path)
            
        except Exception as e:
            logger.error(f"❌ Error publishing audio: {e}")
            
    async def disconnect(self):
        """Disconnect from room"""
        if self.room:
            await self.room.disconnect()
            self.is_connected = False
            logger.info("🔌 TTS disconnected from room")


# Global instance
tts_participant: Optional[TTSRoomParticipant] = None


async def start_tts_participant(room_name: str = "ozzu-main"):
    """Start TTS as room participant"""
    global tts_participant
    
    if tts_participant and tts_participant.is_connected:
        logger.warning("TTS participant already running")
        return tts_participant
    
    tts_participant = TTSRoomParticipant(room_name)
    await tts_participant.connect()
    return tts_participant


async def get_tts_participant() -> TTSRoomParticipant:
    """Get or create TTS participant"""
    global tts_participant
    
    if not tts_participant or not tts_participant.is_connected:
        tts_participant = await start_tts_participant()
    
    return tts_participant