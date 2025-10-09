"""
Audio Stream Processor for WebRTC
Receives audio from WebRTC tracks and prepares for STT processing
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable
from datetime import datetime
import numpy as np
import io

from aiortc import MediaStreamTrack
from av import AudioFrame

from ..config import config

logger = logging.getLogger(__name__)


class AudioProcessor:
    """
    Processes incoming WebRTC audio streams
    Buffers audio and triggers STT when appropriate
    """
    
    def __init__(self):
        self.active_tracks: dict = {}
        self.audio_buffers: dict = {}
        self.processing_tasks: dict = {}
        self.on_audio_ready_callback: Optional[Callable] = None
        
        # Audio buffer settings
        self.buffer_duration_ms = 1000  # 1 second buffer
        self.sample_rate = config.webrtc.sample_rate
        self.channels = config.webrtc.channels
        
        logger.info(f"AudioProcessor initialized (sample_rate={self.sample_rate}, channels={self.channels})")
    
    def set_audio_ready_handler(self, callback: Callable[[str, bytes], Awaitable[None]]):
        """
        Set callback for when audio buffer is ready for processing
        
        Args:
            callback: async function(session_id, audio_bytes)
        """
        self.on_audio_ready_callback = callback
        logger.info("Audio ready handler registered")
    
    async def start_processing_track(self, session_id: str, track: MediaStreamTrack):
        """
        Start processing an audio track from WebRTC
        
        Args:
            session_id: WebSocket session ID
            track: MediaStreamTrack (audio)
        """
        logger.info(f"[{session_id[:8]}] Starting audio track processing...")
        
        # Initialize buffer for this session
        self.audio_buffers[session_id] = {
            "frames": [],
            "total_samples": 0,
            "start_time": datetime.utcnow(),
            "last_frame_time": datetime.utcnow()
        }
        
        self.active_tracks[session_id] = track
        
        # Start processing task
        task = asyncio.create_task(self._process_track(session_id, track))
        self.processing_tasks[session_id] = task
        
        logger.info(f"[{session_id[:8]}] Audio processing started")
    
    async def _process_track(self, session_id: str, track: MediaStreamTrack):
        """
        Process audio frames from track
        
        Args:
            session_id: Session ID
            track: Audio track to process
        """
        try:
            logger.info(f"[{session_id[:8]}] Receiving audio frames...")
            frame_count = 0
            
            while True:
                try:
                    # Receive audio frame from WebRTC
                    frame: AudioFrame = await asyncio.wait_for(track.recv(), timeout=5.0)
                    frame_count += 1
                    
                    # Log first frame
                    if frame_count == 1:
                        logger.info(f"[{session_id[:8]}] 🎤 First audio frame received!")
                        logger.info(f"[{session_id[:8]}]   Sample rate: {frame.sample_rate}")
                        logger.info(f"[{session_id[:8]}]   Channels: {len(frame.layout.channels)}")
                        logger.info(f"[{session_id[:8]}]   Samples: {frame.samples}")
                        logger.info(f"[{session_id[:8]}]   Format: {frame.format.name}")
                    
                    # Process the frame
                    await self._process_audio_frame(session_id, frame)
                    
                    # Log every 100 frames
                    if frame_count % 100 == 0:
                        buffer_info = self.audio_buffers.get(session_id, {})
                        total_samples = buffer_info.get("total_samples", 0)
                        duration_sec = total_samples / self.sample_rate if self.sample_rate > 0 else 0
                        logger.info(f"[{session_id[:8]}] Processed {frame_count} frames ({duration_sec:.2f}s audio)")
                
                except asyncio.TimeoutError:
                    logger.warning(f"[{session_id[:8]}] No audio frame received in 5s")
                    # Check if we should flush buffer
                    await self._check_buffer_timeout(session_id)
                    
                except Exception as e:
                    if "ended" in str(e).lower():
                        logger.info(f"[{session_id[:8]}] Audio track ended normally")
                    else:
                        logger.error(f"[{session_id[:8]}] Error receiving frame: {e}")
                    break
        
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Track processing error: {e}", exc_info=True)
        
        finally:
            logger.info(f"[{session_id[:8]}] Audio processing stopped (processed {frame_count} frames)")
            await self._flush_buffer(session_id)
            self._cleanup_session(session_id)
    
    async def _process_audio_frame(self, session_id: str, frame: AudioFrame):
        """
        Process a single audio frame
        
        Args:
            session_id: Session ID
            frame: AudioFrame from WebRTC
        """
        try:
            # Convert frame to numpy array
            audio_array = frame.to_ndarray()
            
            # If stereo, convert to mono by averaging channels
            if len(audio_array.shape) > 1 and audio_array.shape[0] > 1:
                audio_array = np.mean(audio_array, axis=0)
            
            # Ensure 1D array
            if len(audio_array.shape) > 1:
                audio_array = audio_array.flatten()
            
            # Add to buffer
            buffer = self.audio_buffers.get(session_id)
            if buffer:
                buffer["frames"].append(audio_array)
                buffer["total_samples"] += len(audio_array)
                buffer["last_frame_time"] = datetime.utcnow()
                
                # Check if buffer is full
                duration_ms = (buffer["total_samples"] / self.sample_rate) * 1000
                if duration_ms >= self.buffer_duration_ms:
                    await self._flush_buffer(session_id)
        
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Frame processing error: {e}")
    
    async def _check_buffer_timeout(self, session_id: str):
        """Check if buffer should be flushed due to timeout"""
        buffer = self.audio_buffers.get(session_id)
        if not buffer or len(buffer["frames"]) == 0:
            return
        
        # Check time since last frame
        time_since_last = (datetime.utcnow() - buffer["last_frame_time"]).total_seconds()
        
        if time_since_last > 2.0:  # 2 seconds of silence
            logger.info(f"[{session_id[:8]}] Buffer timeout, flushing...")
            await self._flush_buffer(session_id)
    
    async def _flush_buffer(self, session_id: str):
        """
        Flush audio buffer and send for processing
        
        Args:
            session_id: Session ID
        """
        buffer = self.audio_buffers.get(session_id)
        if not buffer or len(buffer["frames"]) == 0:
            return
        
        try:
            # Concatenate all frames
            audio_data = np.concatenate(buffer["frames"])
            
            # Calculate duration
            duration_sec = len(audio_data) / self.sample_rate
            
            logger.info(f"[{session_id[:8]}] 🎵 Flushing buffer: {duration_sec:.2f}s of audio ({len(audio_data)} samples)")
            
            # Convert to bytes (16-bit PCM)
            audio_int16 = (audio_data * 32767).astype(np.int16)
            audio_bytes = audio_int16.tobytes()
            
            # Call the audio ready handler
            if self.on_audio_ready_callback:
                await self.on_audio_ready_callback(session_id, audio_bytes)
            else:
                logger.warning(f"[{session_id[:8]}] No audio ready handler!")
            
            # Clear buffer
            buffer["frames"] = []
            buffer["total_samples"] = 0
            buffer["start_time"] = datetime.utcnow()
        
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Buffer flush error: {e}")
    
    def _cleanup_session(self, session_id: str):
        """Clean up session resources"""
        if session_id in self.active_tracks:
            del self.active_tracks[session_id]
        if session_id in self.audio_buffers:
            del self.audio_buffers[session_id]
        if session_id in self.processing_tasks:
            del self.processing_tasks[session_id]
        
        logger.info(f"[{session_id[:8]}] Audio processor cleaned up")
    
    async def stop_processing(self, session_id: str):
        """
        Stop processing audio for a session
        
        Args:
            session_id: Session ID
        """
        logger.info(f"[{session_id[:8]}] Stopping audio processing...")
        
        # Cancel processing task
        if session_id in self.processing_tasks:
            task = self.processing_tasks[session_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Flush any remaining buffer
        await self._flush_buffer(session_id)
        
        # Cleanup
        self._cleanup_session(session_id)
        
        logger.info(f"[{session_id[:8]}] Audio processing stopped")
    
    def get_stats(self) -> dict:
        """Get processing statistics"""
        stats = {
            "active_tracks": len(self.active_tracks),
            "sessions": {}
        }
        
        for session_id, buffer in self.audio_buffers.items():
            duration_sec = buffer["total_samples"] / self.sample_rate if self.sample_rate > 0 else 0
            stats["sessions"][session_id[:8]] = {
                "buffered_duration_sec": duration_sec,
                "frame_count": len(buffer["frames"]),
                "total_samples": buffer["total_samples"]
            }
        
        return stats


# Global audio processor instance
audio_processor = AudioProcessor()