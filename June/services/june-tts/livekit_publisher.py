#!/usr/bin/env python3
"""
June TTS Service - LiveKit Integration
Connects to LiveKit room and publishes synthesized audio
"""
import asyncio
import logging
import os
import io
import time
from typing import Optional, Dict, Any
from datetime import datetime

import numpy as np
import torch
import torchaudio
from livekit import rtc, api

logger = logging.getLogger(__name__)


class LiveKitTTSPublisher:
    """Handles LiveKit connection and audio publishing for TTS"""
    
    def __init__(
        self,
        livekit_url: str,
        api_key: str,
        api_secret: str,
        room_name: str = "ozzu-main",
        participant_name: str = "june-tts"
    ):
        self.livekit_url = livekit_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.default_room_name = room_name
        self.participant_name = participant_name
        
        # LiveKit objects
        self.room: Optional[rtc.Room] = None
        self.audio_source: Optional[rtc.AudioSource] = None
        self.audio_track: Optional[rtc.LocalAudioTrack] = None
        self.is_connected = False
        
        # Metrics
        self.chunks_published = 0
        self.total_audio_duration = 0.0
        self.connection_attempts = 0
        
        logger.info(f"LiveKit TTS Publisher initialized: {livekit_url}")
    
    async def connect(self, room_name: Optional[str] = None) -> bool:
        """Connect to LiveKit room"""
        target_room = room_name or self.default_room_name
        self.connection_attempts += 1
        
        try:
            logger.info(f"Connecting to LiveKit room: {target_room}")
            
            # Generate access token
            token = self._generate_token(target_room)
            
            # Create room and audio source
            self.room = rtc.Room()
            self.audio_source = rtc.AudioSource(
                sample_rate=22050,  # CosyVoice2 default
                num_channels=1
            )
            
            # Create audio track from source
            self.audio_track = rtc.LocalAudioTrack.create_audio_track(
                "tts_audio",
                self.audio_source
            )
            
            # Setup room callbacks
            self._setup_room_callbacks()
            
            # Connect to room
            await self.room.connect(self.livekit_url, token)
            
            # Publish audio track
            await self.room.local_participant.publish_track(
                self.audio_track,
                rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_MICROPHONE
                )
            )
            
            self.is_connected = True
            logger.info(f"✅ Connected to LiveKit room: {target_room}")
            return True
            
        except Exception as e:
            logger.error(f"❌ LiveKit connection failed: {e}")
            self.is_connected = False
            return False
    
    def _generate_token(self, room_name: str) -> str:
        """Generate LiveKit access token"""
        token = api.AccessToken(self.api_key, self.api_secret)
        token.with_identity(self.participant_name)
        token.with_name(self.participant_name)
        
        grants = api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=False,  # TTS doesn't need to subscribe
            can_publish_data=True,
        )
        token.with_grants(grants)
        
        return token.to_jwt()
    
    def _setup_room_callbacks(self):
        """Setup LiveKit room event handlers"""
        
        @self.room.on("participant_connected")
        def on_participant_connected(participant):
            logger.info(f"[LK] Participant joined: {participant.identity}")
        
        @self.room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.info(f"[LK] Participant left: {participant.identity}")
        
        @self.room.on("disconnected")
        def on_disconnected():
            logger.warning("[LK] Disconnected from room")
            self.is_connected = False
    
    async def publish_audio(
        self,
        audio_tensor: torch.Tensor,
        sample_rate: int = 22050,
        chunk_size_ms: int = 20
    ) -> bool:
        """
        Publish audio to LiveKit room
        
        Args:
            audio_tensor: Audio tensor (1, samples) or (samples,)
            sample_rate: Audio sample rate
            chunk_size_ms: Chunk size in milliseconds for streaming
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected or not self.audio_source:
            logger.error("Not connected to LiveKit room")
            return False
        
        try:
            start_time = time.time()
            
            # Ensure correct shape and type
            if audio_tensor.dim() == 2:
                audio_tensor = audio_tensor.squeeze(0)
            
            # Convert to numpy and ensure mono
            audio_np = audio_tensor.cpu().numpy()
            if audio_np.ndim > 1:
                audio_np = audio_np.mean(axis=0)
            
            # Resample if needed to match audio source sample rate
            if sample_rate != self.audio_source.sample_rate:
                audio_np = self._resample_audio(
                    audio_np, 
                    sample_rate, 
                    self.audio_source.sample_rate
                )
                sample_rate = self.audio_source.sample_rate
            
            # Convert to int16 for LiveKit
            audio_int16 = (audio_np * 32767).astype(np.int16)
            
            # Calculate chunk size in samples
            chunk_samples = int(sample_rate * chunk_size_ms / 1000)
            
            # Stream audio in chunks
            num_chunks = 0
            for i in range(0, len(audio_int16), chunk_samples):
                chunk = audio_int16[i:i + chunk_samples]
                
                # Pad last chunk if needed
                if len(chunk) < chunk_samples:
                    chunk = np.pad(chunk, (0, chunk_samples - len(chunk)))
                
                # Create audio frame
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=len(chunk)
                )
                
                # Publish frame
                await self.audio_source.capture_frame(frame)
                num_chunks += 1
                
                # Small delay to maintain natural timing
                await asyncio.sleep(chunk_size_ms / 1000)
            
            # Update metrics
            duration = time.time() - start_time
            audio_duration = len(audio_int16) / sample_rate
            self.chunks_published += num_chunks
            self.total_audio_duration += audio_duration
            
            logger.info(
                f"✅ Published audio: {num_chunks} chunks, "
                f"{audio_duration:.2f}s audio in {duration:.2f}s"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Audio publishing failed: {e}", exc_info=True)
            return False
    
    def _resample_audio(
        self, 
        audio: np.ndarray, 
        orig_sr: int, 
        target_sr: int
    ) -> np.ndarray:
        """Resample audio to target sample rate"""
        if orig_sr == target_sr:
            return audio
        
        # Convert to tensor for resampling
        audio_tensor = torch.from_numpy(audio).float()
        resampler = torchaudio.transforms.Resample(orig_sr, target_sr)
        resampled = resampler(audio_tensor)
        
        return resampled.numpy()
    
    async def disconnect(self):
        """Disconnect from LiveKit room"""
        if self.room and self.is_connected:
            try:
                await self.room.disconnect()
                logger.info("Disconnected from LiveKit")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
        
        self.is_connected = False
        self.room = None
        self.audio_source = None
        self.audio_track = None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get publisher statistics"""
        return {
            "is_connected": self.is_connected,
            "chunks_published": self.chunks_published,
            "total_audio_duration": round(self.total_audio_duration, 2),
            "connection_attempts": self.connection_attempts,
            "participant_name": self.participant_name,
            "room_name": self.default_room_name if self.room is None else self.room.name
        }


async def get_livekit_token(
    identity: str,
    room_name: str,
    orchestrator_url: str,
    max_retries: int = 3
) -> tuple[str, str]:
    """Get LiveKit token from orchestrator with retry logic"""
    import httpx
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            timeout = 5.0 + (attempt * 2.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.info(
                    f"Getting LiveKit token from {orchestrator_url}/token "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                
                payload = {
                    "roomName": room_name,
                    "participantName": identity
                }
                
                response = await client.post(
                    f"{orchestrator_url}/token",
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                ws_url = data.get("livekitUrl") or data.get("ws_url")
                token = data["token"]
                
                logger.info("✅ LiveKit token received")
                return ws_url, token
                
        except Exception as e:
            last_error = e
            logger.warning(f"Token request failed: {e}")
            
            if attempt < max_retries - 1:
                wait_time = 2.0 * (attempt + 1)
                await asyncio.sleep(wait_time)
    
    raise RuntimeError(
        f"Failed to get LiveKit token after {max_retries} attempts: {last_error}"
    )


# Example usage
if __name__ == "__main__":
    async def test_publisher():
        # Initialize publisher
        publisher = LiveKitTTSPublisher(
            livekit_url=os.getenv("LIVEKIT_WS_URL", "wss://livekit.ozzu.world"),
            api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
            api_secret=os.getenv("LIVEKIT_API_SECRET", "secret"),
            room_name="test-room"
        )
        
        # Connect
        success = await publisher.connect()
        if not success:
            print("Failed to connect")
            return
        
        # Generate test audio (1 second of sine wave)
        sample_rate = 22050
        duration = 1.0
        frequency = 440.0  # A4 note
        t = torch.linspace(0, duration, int(sample_rate * duration))
        audio = torch.sin(2 * torch.pi * frequency * t)
        
        # Publish audio
        await publisher.publish_audio(audio, sample_rate)
        
        # Wait a bit
        await asyncio.sleep(2)
        
        # Disconnect
        await publisher.disconnect()
        
        # Print stats
        print(publisher.get_stats())
    
    asyncio.run(test_publisher())