"""Partial transcript streaming service for June STT"""
import asyncio
import logging
import time
import tempfile
from datetime import datetime
from typing import Optional, Dict, Set

import numpy as np
import soundfile as sf

from config import config
from whisper_service import whisper_service
from utils.metrics import streaming_metrics
from services.orchestrator_client import notify_orchestrator

logger = logging.getLogger(__name__)

# SOTA Configuration
PARTIAL_CHUNK_MS = 150
PARTIAL_MIN_SPEECH_MS = 200
PARTIAL_EMIT_INTERVAL_MS = 200
MAX_PARTIAL_LENGTH = 120
SAMPLE_RATE = 16000

class PartialTranscriptStreamer:
    """Handles streaming partial transcripts with SOTA optimization"""
    
    def __init__(self, chunk_duration_ms: int = PARTIAL_CHUNK_MS, 
                 min_speech_ms: int = PARTIAL_MIN_SPEECH_MS):
        self.chunk_duration_ms = chunk_duration_ms
        self.min_speech_ms = min_speech_ms
        self.last_partial_text = ""
        self.partial_history: Set[str] = set()
        
    def should_emit_partial(self, partial_text: str) -> bool:
        """Determine if partial should be emitted"""
        if not partial_text or len(partial_text) < 3:
            return False
        
        # Avoid repeating identical partials
        if partial_text == self.last_partial_text:
            return False
        
        # Avoid common false positives
        filtered_words = {"you", "you.", "uh", "um", "mm", "hmm", "yeah", "mhm", "ah", "oh"}
        if partial_text.lower().strip() in filtered_words:
            return False
        
        return True
    
    def update_partial_text(self, text: str):
        """Update the last partial text sent"""
        self.last_partial_text = text
        self.partial_history.add(text)
    
    def reset(self):
        """Reset streamer state"""
        self.last_partial_text = ""
        self.partial_history.clear()


class ContinuousPartialProcessor:
    """Handles continuous partial processing for ultra-fast responses"""
    
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.ultra_fast_partials_enabled = True
        
    async def start_processing(self, participant_id: str, utterance_state, streamer: PartialTranscriptStreamer):
        """Start continuous partial processing for participant"""
        if participant_id in self.active_tasks:
            return  # Already processing
        
        task = asyncio.create_task(
            self._continuous_partial_processor_sota(participant_id, utterance_state, streamer)
        )
        self.active_tasks[participant_id] = task
        logger.info(f"⚡ SOTA: Started ultra-fast partial processing for {participant_id}")
    
    def stop_processing(self, participant_id: str):
        """Stop partial processing for participant"""
        if participant_id in self.active_tasks:
            self.active_tasks[participant_id].cancel()
            del self.active_tasks[participant_id]
            logger.debug(f"🛑 SOTA: Stopped ultra-fast partial task for {participant_id}")
    
    async def _continuous_partial_processor_sota(self, pid: str, state, streamer: PartialTranscriptStreamer):
        """SOTA: Ultra-aggressive continuous partial processing"""
        if not whisper_service.is_model_ready():
            return
        
        utterance_id = state.utterance_id
        
        try:
            while state.is_active:
                try:
                    if state.started_at:
                        duration_ms = (datetime.utcnow() - state.started_at).total_seconds() * 1000
                        
                        # Ultra-fast first partial trigger
                        first_partial_threshold = PARTIAL_MIN_SPEECH_MS
                        if self.ultra_fast_partials_enabled and not state.first_partial_sent:
                            first_partial_threshold = 150  # Ultra-fast mode: 150ms
                        
                        if duration_ms >= first_partial_threshold:
                            await self._process_partial(pid, state, streamer, utterance_id, duration_ms)
                    
                    # Adaptive sleep based on state
                    sleep_duration = PARTIAL_EMIT_INTERVAL_MS / 1000
                    if self.ultra_fast_partials_enabled and not state.first_partial_sent:
                        sleep_duration = 0.1  # Check every 100ms initially
                    
                    await asyncio.sleep(sleep_duration)
                    
                except Exception as e:
                    logger.debug(f"⚠️ SOTA partial loop error for {pid}: {e}")
                    await asyncio.sleep(0.3)
                
        except asyncio.CancelledError:
            logger.debug(f"🛑 SOTA partial processing cancelled for {pid}")
        except Exception as e:
            logger.error(f"❌ Critical SOTA partial error for {pid}: {e}")
    
    async def _process_partial(self, pid: str, state, streamer: PartialTranscriptStreamer, 
                              utterance_id: str, duration_ms: float):
        """Process and emit partial transcript"""
        now = datetime.utcnow()
        emit_interval = PARTIAL_EMIT_INTERVAL_MS
        
        # Faster subsequent partials
        if state.first_partial_sent:
            emit_interval = max(150, PARTIAL_EMIT_INTERVAL_MS - 50)
        
        if (not state.last_partial_sent_at or 
            (now - state.last_partial_sent_at).total_seconds() * 1000 >= emit_interval):
            
            if len(state.buffer) > 0:
                await self._generate_and_send_partial(pid, state, streamer, utterance_id, duration_ms)
    
    async def _generate_and_send_partial(self, pid: str, state, streamer: PartialTranscriptStreamer,
                                       utterance_id: str, duration_ms: float):
        """Generate and send partial transcript"""
        # Optimized audio window
        window_duration = 1.2 if state.first_partial_sent else 0.8
        recent_frames = list(state.buffer)[-int(window_duration * SAMPLE_RATE / 320):]
        
        if recent_frames:
            try:
                partial_audio = np.concatenate(recent_frames, axis=0)
                first_partial_threshold = 150 if self.ultra_fast_partials_enabled else PARTIAL_MIN_SPEECH_MS
                min_samples = int(first_partial_threshold / 1000 * SAMPLE_RATE)
                
                if len(partial_audio) >= min_samples:
                    start_time = time.time()
                    
                    # Fast partial transcription
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                        sf.write(tmp.name, partial_audio, SAMPLE_RATE, subtype='PCM_16')
                        res = await whisper_service.transcribe(tmp.name, language=None)
                    
                    processing_time = (time.time() - start_time) * 1000
                    partial_text = res.get("text", "").strip()
                    
                    # More permissive partial acceptance
                    min_partial_length = 2 if not state.first_partial_sent else 3
                    
                    if (partial_text and len(partial_text) > min_partial_length and 
                        len(partial_text) <= MAX_PARTIAL_LENGTH and
                        streamer.should_emit_partial(partial_text)):
                        
                        state.partial_sequence += 1
                        
                        # Track ultra-fast achievements
                        ultra_fast = False
                        if not state.first_partial_sent and duration_ms < 200:
                            state.ultra_fast_triggered = True
                            state.sota_optimization_used = True
                            ultra_fast = True
                            logger.info(f"🚀 SOTA ULTRA-FAST[{pid}] #{state.partial_sequence} ({processing_time:.0f}ms, {duration_ms:.0f}ms from start): {partial_text}")
                        else:
                            logger.info(f"⚡ SOTA PARTIAL[{pid}] #{state.partial_sequence} ({processing_time:.0f}ms): {partial_text}")
                        
                        # Send optimized partial
                        await notify_orchestrator(
                            pid, partial_text, res.get("language"), 
                            partial=True, utterance_id=utterance_id,
                            partial_sequence=state.partial_sequence,
                            sota_optimized=state.sota_optimization_used
                        )
                        
                        streamer.update_partial_text(partial_text)
                        state.last_partial_sent_at = datetime.utcnow()
                        state.first_partial_sent = True
                        streaming_metrics.record_partial(processing_time, ultra_fast)
            
            except Exception as e:
                logger.debug(f"⚠️ SOTA partial processing error for {pid}: {e}")
    
    def cleanup(self):
        """Cleanup all processing tasks"""
        for pid, task in list(self.active_tasks.items()):
            task.cancel()
        self.active_tasks.clear()
        logger.debug("🧹 SOTA: Cleaned up all partial processing tasks")
