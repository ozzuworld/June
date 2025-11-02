"""LiveKit room management for June STT"""
import asyncio
import logging
from typing import Optional, Dict, Set

from livekit import rtc

from config import config
from livekit_token import connect_room_as_subscriber
from utils.audio_utils import frame_to_float32_mono, resample_to_16k_mono, validate_audio_frame
from services.utterance_manager import UtteranceManager
from services.partial_streamer import ContinuousPartialProcessor
from services.orchestrator_client import orchestrator_client

logger = logging.getLogger(__name__)

EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

class RoomManager:
    """Manages LiveKit room connection and participant handling"""
    
    def __init__(self, utterance_manager: UtteranceManager, 
                 partial_processor: ContinuousPartialProcessor):
        self.room: Optional[rtc.Room] = None
        self.connected = False
        self.utterance_manager = utterance_manager
        self.partial_processor = partial_processor
        self.audio_buffers: Dict[str, list] = {}
        
    async def connect(self):
        """Connect to LiveKit room"""
        if not config.LIVEKIT_ENABLED:
            logger.info("LiveKit disabled, skipping connection")
            return
            
        logger.info("🚀 SOTA: Connecting STT to LiveKit for ultra-responsive voice AI")
        
        try:
            self.room = rtc.Room()
            self._setup_room_callbacks()
            await connect_room_as_subscriber(self.room, "june-stt")
            self.connected = True
            logger.info("✅ SOTA: STT connected with ultra-responsive audio processing")
            
            # Check orchestrator health
            await orchestrator_client.check_health()
            status = "✅ Available" if orchestrator_client.available else "❌ Unavailable"
            logger.info(f"🩺 SOTA: Initial orchestrator status: {status}")
            
        except ConnectionError as e:
            logger.error(f"🔌 SOTA: LiveKit connection failed: {e}")
            logger.info("🔄 SOTA: STT will continue in API-only mode")
            self.connected = False
        except Exception as e:
            logger.error(f"❌ SOTA: LiveKit setup error: {e}")
            logger.info("🔄 SOTA: STT will continue in API-only mode")
            self.connected = False
    
    async def disconnect(self):
        """Disconnect from LiveKit room"""
        if self.room and self.connected:
            try:
                await self.room.disconnect()
                logger.info("👋 SOTA: Disconnected from LiveKit room")
            except Exception as e:
                logger.debug(f"⚠️ LiveKit disconnect error: {e}")
        
        self.partial_processor.cleanup()
        self.connected = False
    
    def _setup_room_callbacks(self):
        """Setup LiveKit room event callbacks"""
        @self.room.on("participant_connected")
        def _participant_join(participant):
            logger.info(f"👤 SOTA: Participant joined: {participant.identity}")
            if participant.identity in EXCLUDE_PARTICIPANTS:
                logger.info(f"🚫 SOTA: Participant {participant.identity} is EXCLUDED from STT processing")
            else:
                self.utterance_manager.ensure_utterance_state(participant.identity)
                self._ensure_audio_buffer(participant.identity)
                logger.info(f"✅ SOTA: Initialized ultra-responsive state for participant: {participant.identity}")

        @self.room.on("participant_disconnected")
        def _participant_leave(participant):
            logger.info(f"👋 SOTA: Participant left: {participant.identity}")
            
            pid = participant.identity
            if pid in self.audio_buffers:
                del self.audio_buffers[pid]
            
            self.utterance_manager.cleanup_participant(pid)
            self.partial_processor.stop_processing(pid)

        @self.room.on("track_subscribed")
        def _track_subscribed(track: rtc.Track, publication, participant):
            logger.info(f"🎵 SOTA TRACK SUBSCRIBED: kind={track.kind}, participant={participant.identity}")
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            
            pid = participant.identity or participant.sid
            if pid in EXCLUDE_PARTICIPANTS:
                logger.info(f"🚫 SOTA: EXCLUDED participant {pid} - not processing audio")
                return
            
            logger.info(f"✅ SOTA: Subscribed to ultra-responsive audio processing of {pid}")
            
            self.utterance_manager.ensure_utterance_state(pid)
            self._ensure_audio_buffer(pid)
            
            stream = rtc.AudioStream(track)
            
            async def consume_audio():
                logger.info(f"🎧 SOTA: Starting ultra-fast audio consumption for {pid}")
                async for event in stream:
                    await self._process_audio_frame(pid, event.frame)
            
            asyncio.create_task(consume_audio())
    
    def _ensure_audio_buffer(self, participant_id: str):
        """Ensure audio buffer exists for participant"""
        if participant_id not in self.audio_buffers:
            self.audio_buffers[participant_id] = []
    
    async def _process_audio_frame(self, participant_id: str, frame: rtc.AudioFrame):
        """Process incoming audio frame from participant"""
        if participant_id in EXCLUDE_PARTICIPANTS or "tts" in participant_id.lower():
            return
        
        if not validate_audio_frame(frame):
            return
            
        try:
            pcm, sr = frame_to_float32_mono(frame)
            pcm16k = resample_to_16k_mono(pcm, sr)
            
            # Store in buffer for main processing loop
            self._ensure_audio_buffer(participant_id)
            self.audio_buffers[participant_id].append(pcm16k)
            
        except Exception as e:
            logger.debug(f"⚠️ SOTA audio frame processing error for {participant_id}: {e}")
    
    def get_buffered_audio(self, participant_id: str) -> list:
        """Get and clear buffered audio for participant"""
        if participant_id not in self.audio_buffers:
            return []
        
        frames = self.audio_buffers[participant_id].copy()
        self.audio_buffers[participant_id].clear()
        return frames
    
    def get_stats(self) -> dict:
        """Get room manager statistics"""
        return {
            "connected": self.connected,
            "livekit_enabled": config.LIVEKIT_ENABLED,
            "active_audio_buffers": len(self.audio_buffers),
            "total_participants": len(self.audio_buffers),
            "excluded_participants": list(EXCLUDE_PARTICIPANTS)
        }
