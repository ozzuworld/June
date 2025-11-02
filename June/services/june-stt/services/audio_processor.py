"""Main audio processing service for June STT"""
import asyncio
import logging
import tempfile
import time
from datetime import datetime
from typing import Dict, List

import numpy as np
import soundfile as sf

from config import config
from whisper_service import whisper_service
from services.utterance_manager import UtteranceManager
from services.partial_streamer import ContinuousPartialProcessor, PartialTranscriptStreamer
from services.room_manager import RoomManager
from services.orchestrator_client import orchestrator_client
from utils.metrics import streaming_metrics

logger = logging.getLogger(__name__)

# SOTA Configuration
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 8.0
MIN_UTTERANCE_SEC = 0.3
PROCESS_SLEEP_SEC = 0.03
SILENCE_TIMEOUT_SEC = 0.8
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

class AudioProcessor:
    """Main audio processing service with SOTA optimization"""
    
    def __init__(self):
        self.utterance_manager = UtteranceManager()
        self.partial_processor = ContinuousPartialProcessor()
        self.room_manager: RoomManager = None
        self.partial_streamers: Dict[str, PartialTranscriptStreamer] = {}
        
        # Processing state
        self.processing_task: asyncio.Task = None
        self.health_check_task: asyncio.Task = None
        self.processed_utterances = 0
        
    async def initialize(self):
        """Initialize audio processing components"""
        logger.info("🚀 SOTA: Initializing audio processing with competitive optimization")
        
        # Initialize Whisper service
        await whisper_service.initialize()
        logger.info("✅ SOTA: Enhanced Whisper + Aggressive Silero VAD ready")
        
        # Initialize room manager
        self.room_manager = RoomManager(self.utterance_manager, self.partial_processor)
        await self.room_manager.connect()
        
        # Start processing tasks
        if self.room_manager.connected:
            self.processing_task = asyncio.create_task(self._main_processing_loop())
            logger.info("✅ SOTA: ULTRA-RESPONSIVE STREAMING PIPELINE active")
        else:
            logger.info("⚠️ SOTA: STT running in enhanced API-only mode")
        
        # Start health monitoring
        self.health_check_task = asyncio.create_task(self._health_monitor())
        
    async def cleanup(self):
        """Cleanup all resources"""
        logger.info("🧹 SOTA: Cleaning up audio processor")
        
        # Cancel processing tasks
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
        
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        # Cleanup components
        self.partial_processor.cleanup()
        
        if self.room_manager:
            await self.room_manager.disconnect()
    
    def _ensure_partial_streamer(self, participant_id: str) -> PartialTranscriptStreamer:
        """Ensure partial streamer exists for participant"""
        if participant_id not in self.partial_streamers:
            self.partial_streamers[participant_id] = PartialTranscriptStreamer(
                chunk_duration_ms=150,
                min_speech_ms=200,
            )
            logger.debug(f"⚡ SOTA: Created ultra-fast partial streamer for {participant_id}")
        return self.partial_streamers[participant_id]
    
    async def _main_processing_loop(self):
        """Main processing loop optimized for competitive voice AI performance"""
        logger.info("🚀 SOTA: Starting ultra-responsive STT processing for competitive voice AI")
        logger.info("🎯 SOTA TARGET: <700ms total pipeline (OpenAI/Google competitive)")
        
        while True:
            try:
                await self._process_all_participants()
                await asyncio.sleep(PROCESS_SLEEP_SEC)
            except Exception as e:
                logger.warning(f"❌ SOTA main loop error: {e}")
                await asyncio.sleep(0.1)
    
    async def _process_all_participants(self):
        """Process audio for all participants"""
        if not self.room_manager:
            return
        
        for participant_id in list(self.room_manager.audio_buffers.keys()):
            if participant_id in EXCLUDE_PARTICIPANTS or "tts" in participant_id.lower():
                continue
            
            try:
                await self._process_participant_audio(participant_id)
            except Exception as e:
                logger.debug(f"⚠️ SOTA participant processing error for {participant_id}: {e}")
    
    async def _process_participant_audio(self, participant_id: str):
        """Process audio for a specific participant"""
        # Get buffered audio frames
        frames = self.room_manager.get_buffered_audio(participant_id)
        if not frames:
            return
        
        state = self.utterance_manager.ensure_utterance_state(participant_id)
        streamer = self._ensure_partial_streamer(participant_id)
        
        for frame in frames:
            await self._process_audio_frame(participant_id, frame, state, streamer)
    
    async def _process_audio_frame(self, participant_id: str, frame: np.ndarray, 
                                 state, streamer: PartialTranscriptStreamer):
        """Process individual audio frame"""
        now = datetime.utcnow()
        
        if not state.is_active:
            # Start new utterance
            state.is_active = True
            state.started_at = now
            state.last_audio_at = now
            state.buffer.clear()
            state.buffer.append(frame)
            state.total_samples = len(frame)
            state.first_partial_sent = False
            state.last_partial_sent_at = None
            state.partial_sequence = 0
            state.utterance_id = f"{participant_id}_{int(time.time() * 1000)}"
            state.ultra_fast_triggered = False
            state.sota_optimization_used = False
            
            if streamer:
                streamer.reset()
            
            logger.debug(f"🚀 SOTA: Started ultra-fast utterance capture for {participant_id} (ID: {state.utterance_id[-12:]})")
            
            # Start continuous partial processing
            await self.partial_processor.start_processing(participant_id, state, streamer)
        
        else:
            # Continue existing utterance
            state.buffer.append(frame)
            state.total_samples += len(frame)
            state.last_audio_at = now
            
            duration = (now - state.started_at).total_seconds()
            silence_duration = (now - state.last_audio_at).total_seconds()
            
            # Check if utterance should end
            should_end = (
                duration >= MAX_UTTERANCE_SEC or
                (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)
            )
            
            if should_end:
                await self._finalize_utterance(participant_id, state, streamer)
    
    async def _finalize_utterance(self, participant_id: str, state, streamer: PartialTranscriptStreamer):
        """Finalize and transcribe complete utterance"""
        # Stop partial processing
        self.partial_processor.stop_processing(participant_id)
        
        if len(state.buffer) > 0:
            utterance_audio = np.concatenate(list(state.buffer), axis=0)
            utterance_duration = len(utterance_audio) / SAMPLE_RATE
            utterance_id = state.utterance_id
            
            perf_note = ""
            if state.ultra_fast_triggered:
                perf_note = " (ULTRA-FAST ACHIEVED)"
            
            logger.info(f"🎬 SOTA: Ending utterance for {participant_id}: {utterance_duration:.2f}s (ID: {utterance_id[-12:]}){perf_note}")
            
            await self._transcribe_final_utterance(participant_id, utterance_audio, utterance_id)
        
        # Reset state
        self.utterance_manager.reset_utterance_state(participant_id)
        if streamer:
            streamer.reset()
    
    async def _transcribe_final_utterance(self, participant_id: str, audio: np.ndarray, utterance_id: str):
        """Transcribe final utterance with performance tracking"""
        if not whisper_service.is_model_ready():
            logger.warning("⚠️ Whisper model not ready")
            return
        
        try:
            duration = len(audio) / SAMPLE_RATE
            
            # SOTA: Enhanced speech validation
            if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
                logger.debug(f"🔇 SOTA VAD filtered out non-speech for {participant_id} ({duration:.2f}s)")
                return
            
            logger.info(f"🎯 SOTA VAD confirmed speech for {participant_id}: {duration:.2f}s (ID: {utterance_id[-12:]})")
            
            start_time = time.time()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
                res = await whisper_service.transcribe(tmp.name, language=None)
            
            processing_time = (time.time() - start_time) * 1000
            text = res.get("text", "").strip()
            method = res.get("method", "sota_enhanced")
            
            if text and len(text) > 1:
                # Filter common false positives
                filtered_words = {"you", "you.", "uh", "um", "mm", "hmm", "yeah", "mhm", "ah", "oh"}
                if text.lower() not in filtered_words:
                    logger.info(f"✅ SOTA FINAL[{participant_id}] via {method} ({processing_time:.0f}ms): {text}")
                    await orchestrator_client.notify_transcript(
                        participant_id, text, res.get("language"), 
                        partial=False, sota_optimized=True
                    )
                    self.processed_utterances += 1
                    streaming_metrics.record_final(processing_time)
                else:
                    logger.debug(f"😫 SOTA: Filtered false positive: '{text}'")
            else:
                logger.debug(f"🔇 SOTA: Empty transcription result for {participant_id}")
        
        except Exception as e:
            logger.error(f"❌ SOTA transcription error for {participant_id}: {e}")
    
    async def _health_monitor(self):
        """Monitor orchestrator health periodically"""
        while True:
            try:
                await orchestrator_client.check_health()
                status = "✅ Available" if orchestrator_client.available else "❌ Unavailable"
                logger.debug(f"🩺 SOTA: Orchestrator health: {status}")
                await asyncio.sleep(20.0)  # Check every 20 seconds
            except Exception as e:
                logger.debug(f"⚠️ Health monitor error: {e}")
                await asyncio.sleep(5.0)
    
    def get_stats(self) -> dict:
        """Get audio processor statistics"""
        return {
            "processed_utterances": self.processed_utterances,
            "partial_transcripts_sent": orchestrator_client.partial_transcripts_sent,
            "active_partial_streamers": len(self.partial_streamers),
            "utterance_stats": self.utterance_manager.get_stats(),
            "room_stats": self.room_manager.get_stats() if self.room_manager else {},
            "orchestrator_stats": orchestrator_client.get_stats(),
            "streaming_metrics": streaming_metrics.get_stats(),
        }
