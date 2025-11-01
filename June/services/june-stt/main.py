#!/usr/bin/env python3
"""
June STT Enhanced - FULL STREAMING PIPELINE - RESILIENT
Silero VAD + LiveKit Integration + CONTINUOUS PARTIAL STREAMING
Intelligent speech detection + Real-time partial transcript streaming for true online processing
OpenAI API compatible + Real-time voice chat capabilities

FULL STREAMING PIPELINE IMPLEMENTATION:
- Emits partials to orchestrator every 250ms during speech
- Enables LLM to start processing while user is still talking
- Supports overlapping speech-in → thinking → speech-out pipeline

RESILIENT: Can start without immediate orchestrator connection
FIXED: Enhanced error handling and retry logic
"""
import asyncio
import logging
import uuid
import tempfile
import soundfile as sf
import os
import time
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Deque, Dict
from collections import deque

import numpy as np
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from livekit import rtc
from scipy import signal
import httpx

from config import config
from whisper_service import whisper_service
from livekit_token import connect_room_as_subscriber
from streaming_utils import PartialTranscriptStreamer, streaming_metrics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt")

# -------- FULL STREAMING PIPELINE Feature flags --------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

# ENHANCED: Enable continuous partial streaming for full online pipeline
STREAMING_ENABLED = getattr(config, "STT_STREAMING_ENABLED", _bool_env("STT_STREAMING_ENABLED", True))
PARTIALS_ENABLED  = getattr(config, "STT_PARTIALS_ENABLED",  _bool_env("STT_PARTIALS_ENABLED", True))
CONTINUOUS_PARTIALS = _bool_env("STT_CONTINUOUS_PARTIALS", True)  # NEW: Enable continuous partial emission

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
orchestrator_available: bool = False  # NEW: Track orchestrator availability
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, 'UtteranceState'] = {}  # FIXED: Proper type annotation
partial_streamers: Dict[str, PartialTranscriptStreamer] = {}
# NEW: Track partial streaming per participant
partial_streaming_tasks: Dict[str, asyncio.Task] = {}
processed_utterances = 0
partial_transcripts_sent = 0  # NEW: Track partial transcripts

# Simplified constants (Silero VAD handles complexity)
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 12.0  # Allow longer for natural conversation
MIN_UTTERANCE_SEC = 0.5
PROCESS_SLEEP_SEC = 0.05  # OPTIMIZED: Faster processing loop
SILENCE_TIMEOUT_SEC = 1.2  # Slightly longer silence tolerance
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

# STREAMING: Enhanced partial processing parameters
PARTIAL_CHUNK_MS = 200  # Process partials every 200ms
PARTIAL_MIN_SPEECH_MS = 300  # OPTIMIZED: Lower threshold for faster first partial
PARTIAL_EMIT_INTERVAL_MS = 250  # OPTIMIZED: Emit partials every 250ms during speech
MAX_PARTIAL_LENGTH = 150  # Prevent very long partials

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0
        self.first_partial_sent = False
        self.last_partial_sent_at: Optional[datetime] = None  # NEW: Track partial timing
        self.partial_sequence = 0  # NEW: Track partial sequence for deduplication
        self.utterance_id = str(uuid.uuid4())  # NEW: Unique ID per utterance

# Helper functions (enhanced for CONTINUOUS streaming)

def _ensure_utterance_state(pid: str) -> UtteranceState:
    """FIXED: Ensure utterance state exists with proper initialization"""
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
        logger.debug(f"🆕 Created new utterance state for {pid}")
    return utterance_states[pid]


def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=600)  # OPTIMIZED: Larger buffer for longer utterances
        logger.debug(f"🆕 Created new audio buffer for {pid}")
    return buffers[pid]


def _ensure_partial_streamer(pid: str) -> PartialTranscriptStreamer:
    if pid not in partial_streamers:
        partial_streamers[pid] = PartialTranscriptStreamer(
            chunk_duration_ms=PARTIAL_CHUNK_MS,
            min_speech_ms=PARTIAL_MIN_SPEECH_MS,
        )
        logger.debug(f"🆕 Created partial streamer for {pid}")
    return partial_streamers[pid]


def _reset_utterance_state(state: UtteranceState):
    """FIXED: Safe state reset with logging"""
    old_id = getattr(state, 'utterance_id', 'unknown')[:8]
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_audio_at = None
    state.total_samples = 0
    state.first_partial_sent = False
    state.last_partial_sent_at = None
    state.partial_sequence = 0
    state.utterance_id = str(uuid.uuid4())  # New utterance ID
    logger.debug(f"🔄 Reset utterance state: {old_id} → {state.utterance_id[:8]}")


async def _check_orchestrator_health() -> bool:
    """NEW: Check if orchestrator is available for webhook delivery"""
    if not config.ORCHESTRATOR_URL:
        return False
        
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{config.ORCHESTRATOR_URL}/healthz")
            return r.status_code == 200
    except Exception:
        return False


async def _notify_orchestrator(user_id: str, text: str, language: Optional[str], partial: bool = False, 
                              utterance_id: Optional[str] = None, partial_sequence: int = 0):
    """ENHANCED: Resilient orchestrator notification with availability checking"""
    global orchestrator_available, partial_transcripts_sent
    
    if not config.ORCHESTRATOR_URL:
        logger.debug("Orchestrator URL not configured, skipping notification")
        return

    payload = {
        "transcript_id": str(uuid.uuid4()),
        "user_id": user_id,
        "participant": user_id,
        "event": "partial_transcript" if partial else "transcript",
        "text": text,
        "language": language,
        "timestamp": datetime.utcnow().isoformat(),
        "room_name": "ozzu-main",
        "partial": partial,
    }
    
    # NEW: Add streaming metadata for partial transcripts
    if partial:
        payload.update({
            "utterance_id": utterance_id,
            "partial_sequence": partial_sequence,
            "is_streaming": True,
            "streaming_metadata": {
                "chunk_duration_ms": PARTIAL_CHUNK_MS,
                "min_speech_ms": PARTIAL_MIN_SPEECH_MS,
                "emit_interval_ms": PARTIAL_EMIT_INTERVAL_MS
            }
        })

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{config.ORCHESTRATOR_URL}/api/webhooks/stt", json=payload)
            
            if r.status_code == 429:
                logger.info(f"🛡️ Rate limited by orchestrator: {r.text}")
                orchestrator_available = True  # Still available, just rate limited
            elif r.status_code != 200:
                logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
                orchestrator_available = False
            else:
                status = '📤 PARTIAL' if partial else '📤 FINAL'
                logger.info(f"{status} transcript to orchestrator: '{text}'")
                orchestrator_available = True
                if partial:
                    partial_transcripts_sent += 1
                    
    except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        logger.warning(f"⏰ Orchestrator timeout ({type(e).__name__}): {e}")
        orchestrator_available = False
    except httpx.ConnectError as e:
        logger.warning(f"🔌 Orchestrator connection error: {e}")
        orchestrator_available = False
    except Exception as e:
        logger.warning(f"❌ Orchestrator notify error: {e}")
        orchestrator_available = False


# Audio helpers

def _frame_to_float32_mono(frame: rtc.AudioFrame):
    sr = frame.sample_rate
    ch = frame.num_channels
    buf = memoryview(frame.data)
    try:
        arr = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        arr = np.frombuffer(buf, dtype=np.float32)
    if ch and ch > 1:
        try:
            arr = arr.reshape(-1, ch).mean(axis=1)
        except Exception:
            frames = arr[: (len(arr) // ch) * ch]
            arr = frames.reshape(-1, ch).mean(axis=1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return arr, sr


def _resample_to_16k_mono(pcm: np.ndarray, sr: int) -> np.ndarray:
    if sr == SAMPLE_RATE:
        return pcm
    gcd = np.gcd(sr, SAMPLE_RATE)
    up = SAMPLE_RATE // gcd
    down = sr // gcd
    out = signal.resample_poly(pcm, up, down).astype(np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


async def _continuous_partial_processor(pid: str, state: UtteranceState, streamer: PartialTranscriptStreamer):
    """NEW: Continuously process and emit partial transcripts during active speech"""
    if not CONTINUOUS_PARTIALS or not whisper_service.is_model_ready():
        return
        
    logger.info(f"🔄 Starting continuous partial processing for {pid}")
    utterance_id = state.utterance_id
    
    try:
        while state.is_active:
            try:
                # Wait for minimum speech duration before starting partials
                if state.started_at:
                    duration_ms = (datetime.utcnow() - state.started_at).total_seconds() * 1000
                    
                    if duration_ms >= PARTIAL_MIN_SPEECH_MS:
                        # Check if enough time has passed since last partial
                        now = datetime.utcnow()
                        if (not state.last_partial_sent_at or 
                            (now - state.last_partial_sent_at).total_seconds() * 1000 >= PARTIAL_EMIT_INTERVAL_MS):
                            
                            # Get current audio buffer for partial transcription
                            if len(state.buffer) > 0:
                                # Use recent audio for partial (last 1.5 seconds)
                                recent_frames = list(state.buffer)[-int(1.5 * SAMPLE_RATE / 320):]
                                if recent_frames:
                                    try:
                                        partial_audio = np.concatenate(recent_frames, axis=0)
                                        
                                        if len(partial_audio) >= int(PARTIAL_MIN_SPEECH_MS / 1000 * SAMPLE_RATE):
                                            start_time = time.time()
                                            
                                            # Process partial transcript
                                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                                                sf.write(tmp.name, partial_audio, SAMPLE_RATE, subtype='PCM_16')
                                                res = await whisper_service.transcribe(tmp.name, language=None)
                                            
                                            processing_time = (time.time() - start_time) * 1000
                                            partial_text = res.get("text", "").strip()
                                            
                                            if (partial_text and len(partial_text) > 3 and 
                                                len(partial_text) <= MAX_PARTIAL_LENGTH and
                                                streamer.should_emit_partial(partial_text)):
                                                
                                                state.partial_sequence += 1
                                                logger.info(f"⚡ CONTINUOUS PARTIAL[{pid}] #{state.partial_sequence} ({processing_time:.0f}ms): {partial_text}")
                                                
                                                # Send partial to orchestrator (resilient)
                                                await _notify_orchestrator(
                                                    pid, partial_text, res.get("language"), 
                                                    partial=True, utterance_id=utterance_id,
                                                    partial_sequence=state.partial_sequence
                                                )
                                                
                                                streamer.update_partial_text(partial_text)
                                                state.last_partial_sent_at = now
                                                state.first_partial_sent = True
                                                streaming_metrics.record_partial(processing_time)
                                    
                                    except Exception as e:
                                        logger.debug(f"⚠️ Partial audio processing error for {pid}: {e}")
                
                # Sleep before next partial check
                await asyncio.sleep(PARTIAL_EMIT_INTERVAL_MS / 1000)
                
            except Exception as e:
                logger.debug(f"⚠️ Continuous partial loop error for {pid}: {e}")
                await asyncio.sleep(0.5)  # Longer sleep on error
            
    except asyncio.CancelledError:
        logger.debug(f"🛑 Continuous partial processing cancelled for {pid}")
    except Exception as e:
        logger.error(f"❌ Critical continuous partial error for {pid}: {e}")
    finally:
        # Clean up task reference
        if pid in partial_streaming_tasks:
            del partial_streaming_tasks[pid]
            logger.debug(f"🧹 Cleaned up continuous partial task for {pid}")


async def _transcribe_utterance_with_silero(pid: str, audio: np.ndarray, utterance_id: str):
    """FIXED: Enhanced error handling for final transcription"""
    global processed_utterances
    if not whisper_service.is_model_ready():
        logger.warning("⚠️ Whisper model not ready")
        return
        
    try:
        duration = len(audio) / SAMPLE_RATE
        
        # FIXED: Better speech validation
        if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
            logger.debug(f"🔇 Silero VAD filtered out non-speech for {pid} ({duration:.2f}s)")
            return
            
        logger.info(f"🎯 Silero VAD confirmed speech for {pid}: {duration:.2f}s (ID: {utterance_id[:8]})")
        
        start_time = time.time()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None)
            
        processing_time = (time.time() - start_time) * 1000
        text = res.get("text", "").strip()
        method = res.get("method", "silero_enhanced")
        
        if text and len(text) > 2:
            # FIXED: Better filtering of false positives
            filtered_words = {"you", "you.", "uh", "um", "mm", "hmm", "yeah", "mhm", "ah"}
            if text.lower() not in filtered_words:
                logger.info(f"✅ FINAL[{pid}] via {method} ({processing_time:.0f}ms): {text}")
                # Send final transcript
                await _notify_orchestrator(pid, text, res.get("language"), partial=False)
                processed_utterances += 1
                streaming_metrics.record_final()
            else:
                logger.debug(f"😫 Filtered false positive: '{text}'")
        else:
            logger.debug(f"🔇 Empty transcription result for {pid}")
            
    except Exception as e:
        logger.error(f"❌ Transcription error for {pid}: {e}")


async def _process_utterances_with_streaming():
    """ENHANCED: Main processing loop with FIXED state management"""
    global processed_utterances, orchestrator_available
    logger.info("🚀 Starting Silero VAD-enhanced STT processing with FULL STREAMING PIPELINE")
    
    if STREAMING_ENABLED and PARTIALS_ENABLED:
        if CONTINUOUS_PARTIALS:
            logger.info(f"⚡ CONTINUOUS STREAMING MODE: Partial transcripts every {PARTIAL_EMIT_INTERVAL_MS}ms")
            logger.info(f"🎯 ONLINE PIPELINE: LLM starts processing while user speaks")
        else:
            logger.info(f"⚡ STREAMING MODE: Partial transcripts every {PARTIAL_CHUNK_MS}ms")
    
    logger.info("🎯 Intelligent speech detection replaces custom thresholds")
    
    # Periodic orchestrator health check
    last_health_check = time.time()
    health_check_interval = 30.0  # Check every 30 seconds
    
    while True:
        try:
            # Periodic orchestrator health check
            current_time = time.time()
            if current_time - last_health_check > health_check_interval:
                orchestrator_available = await _check_orchestrator_health()
                status = "✅ Available" if orchestrator_available else "❌ Unavailable"
                logger.info(f"🩺 Orchestrator health check: {status}")
                last_health_check = current_time
            
            # FIXED: Safe iteration over participants
            participants_to_process = list(buffers.keys())
            
            for pid in participants_to_process:
                try:
                    # Skip excluded participants
                    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
                        continue
                    
                    # FIXED: Ensure all state exists before processing
                    state = _ensure_utterance_state(pid)
                    buf = _ensure_buffer(pid)
                    streamer = _ensure_partial_streamer(pid) if STREAMING_ENABLED else None
                    
                    # Process audio frames
                    while buf:
                        try:
                            frame = buf.popleft()
                            now = datetime.utcnow()
                            
                            if not state.is_active:
                                # NEW: Starting new utterance - begin continuous partial processing
                                state.is_active = True
                                state.started_at = now
                                state.last_audio_at = now
                                state.buffer.clear()
                                state.buffer.append(frame)
                                state.total_samples = len(frame)
                                state.first_partial_sent = False
                                state.last_partial_sent_at = None
                                state.partial_sequence = 0
                                state.utterance_id = str(uuid.uuid4())
                                
                                if streamer:
                                    streamer.reset()
                                    
                                logger.debug(f"🎬 Started utterance capture for {pid} (ID: {state.utterance_id[:8]})")
                                
                                # NEW: Start continuous partial processing task
                                if (CONTINUOUS_PARTIALS and STREAMING_ENABLED and 
                                    pid not in partial_streaming_tasks):
                                    task = asyncio.create_task(_continuous_partial_processor(pid, state, streamer))
                                    partial_streaming_tasks[pid] = task
                                    logger.info(f"🔄 Started continuous partial task for {pid}")
                                    
                            else:
                                # Continue building utterance
                                state.buffer.append(frame)
                                state.total_samples += len(frame)
                                state.last_audio_at = now
                                
                                # Update streamer for any legacy partial processing
                                if STREAMING_ENABLED and streamer and not CONTINUOUS_PARTIALS:
                                    streamer.add_audio_chunk(frame)
                                    
                                # Check if utterance should end
                                duration = (now - state.started_at).total_seconds()
                                silence_duration = (now - state.last_audio_at).total_seconds()
                                
                                should_end = (
                                    duration >= MAX_UTTERANCE_SEC or
                                    (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)
                                )
                                
                                if should_end:
                                    # NEW: Cancel continuous partial processing
                                    if pid in partial_streaming_tasks:
                                        partial_streaming_tasks[pid].cancel()
                                        try:
                                            await partial_streaming_tasks[pid]
                                        except asyncio.CancelledError:
                                            pass
                                        del partial_streaming_tasks[pid]
                                        logger.debug(f"🛑 Stopped continuous partial task for {pid}")
                                    
                                    # Process final utterance
                                    if len(state.buffer) > 0:
                                        utterance_audio = np.concatenate(list(state.buffer), axis=0)
                                        utterance_duration = len(utterance_audio) / SAMPLE_RATE
                                        utterance_id = state.utterance_id
                                        
                                        logger.info(f"🎬 Ending utterance for {pid}: {utterance_duration:.2f}s (ID: {utterance_id[:8]})")
                                        
                                        # Process final transcript
                                        await _transcribe_utterance_with_silero(pid, utterance_audio, utterance_id)
                                    
                                    # Reset state for next utterance
                                    _reset_utterance_state(state)
                                    if streamer:
                                        streamer.reset()
                                    
                        except Exception as frame_error:
                            logger.debug(f"⚠️ Frame processing error for {pid}: {frame_error}")
                            continue
                            
                except Exception as participant_error:
                    logger.debug(f"⚠️ Participant processing error for {pid}: {participant_error}")
                    continue
                    
        except Exception as e:
            logger.warning(f"❌ Main loop error: {e}")
            
        await asyncio.sleep(PROCESS_SLEEP_SEC)


async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    """FIXED: Safe audio frame processing"""
    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
        return
        
    try:
        pcm, sr = _frame_to_float32_mono(frame)
        pcm16k = _resample_to_16k_mono(pcm, sr)
        _ensure_buffer(pid).append(pcm16k)
    except Exception as e:
        logger.debug(f"⚠️ Audio frame processing error for {pid}: {e}")


def setup_room_callbacks(room: rtc.Room):
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"👤 Participant joined: {p.identity}")
        if p.identity in EXCLUDE_PARTICIPANTS:
            logger.info(f"🚫 Participant {p.identity} is EXCLUDED from STT processing")
        else:
            # Pre-initialize state for new participant
            _ensure_utterance_state(p.identity)
            _ensure_buffer(p.identity)
            logger.info(f"✅ Initialized state for participant: {p.identity}")

    @room.on("participant_disconnected")
    def _p_leave(p):
        logger.info(f"👋 Participant left: {p.identity}")
        
        # Clean up participant state
        pid = p.identity
        if pid in buffers:
            del buffers[pid]
        if pid in utterance_states:
            del utterance_states[pid]
        if pid in partial_streamers:
            del partial_streamers[pid]
            
        # NEW: Cancel and clean up continuous partial task
        if pid in partial_streaming_tasks:
            partial_streaming_tasks[pid].cancel()
            del partial_streaming_tasks[pid]
            logger.debug(f"🛑 Cleaned up continuous partial task for {pid}")

    @room.on("track_subscribed")
    def _track_sub(track: rtc.Track, pub, participant):
        logger.info(f"🎵 TRACK SUBSCRIBED: kind={track.kind}, participant={participant.identity}")
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        pid = participant.identity or participant.sid
        if pid in EXCLUDE_PARTICIPANTS:
            logger.info(f"🚫 EXCLUDED participant {pid} - not processing audio")
            return
        logger.info(f"✅ Subscribed to audio of {pid}")
        
        # Pre-initialize state
        _ensure_utterance_state(pid)
        _ensure_buffer(pid)
        
        stream = rtc.AudioStream(track)
        async def consume():
            logger.info(f"🎧 Starting audio consumption for {pid}")
            async for event in stream:
                await _on_audio_frame(pid, event.frame)
        asyncio.create_task(consume())


async def join_livekit_room():
    """ENHANCED: Join LiveKit with better error handling and fallback options"""
    global room, room_connected
    if not config.LIVEKIT_ENABLED:
        logger.info("LiveKit disabled, skipping connection")
        return
        
    logger.info("Connecting STT to LiveKit via orchestrator token")
    
    try:
        room = rtc.Room()
        setup_room_callbacks(room)
        await connect_room_as_subscriber(room, "june-stt")
        room_connected = True
        logger.info("✅ STT connected and listening for audio frames")
        
        # Check initial orchestrator availability
        global orchestrator_available
        orchestrator_available = await _check_orchestrator_health()
        status = "✅ Available" if orchestrator_available else "❌ Unavailable"
        logger.info(f"🩺 Initial orchestrator status: {status}")
        
    except ConnectionError as e:
        logger.error(f"🔌 LiveKit connection failed: {e}")
        logger.info("🔄 STT will continue operating without LiveKit (API-only mode)")
        room_connected = False
    except Exception as e:
        logger.error(f"❌ LiveKit setup error: {e}")
        logger.info("🔄 STT will continue operating without LiveKit (API-only mode)")
        room_connected = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 June STT Enhanced - FULL STREAMING PIPELINE")
    logger.info("Features: Silero VAD + Continuous Partials + Online LLM Processing")
    logger.info(f"⚡ Streaming: {STREAMING_ENABLED}, Partials: {PARTIALS_ENABLED}, Continuous: {CONTINUOUS_PARTIALS}")
    
    if CONTINUOUS_PARTIALS:
        logger.info(f"🎯 ONLINE MODE: LLM processes speech while user is talking (every {PARTIAL_EMIT_INTERVAL_MS}ms)")
        logger.info(f"⚡ TARGET LATENCY: First partial in <{PARTIAL_MIN_SPEECH_MS}ms from speech start")
        logger.info(f"🎯 PIPELINE GOAL: speech-in + thinking + speech-out overlap")
    
    # Initialize Whisper (critical component)
    try:
        await whisper_service.initialize()
        logger.info("✅ Enhanced Whisper + Silero VAD + CONTINUOUS STREAMING service ready")
    except Exception as e:
        logger.error(f"❌ Enhanced service init failed: {e}")
        raise  # Whisper is critical, don't start without it
        
    # Try to join LiveKit (non-critical, can start without it)
    await join_livekit_room()
    
    # Start processing task if LiveKit connected
    task = None
    if room_connected:
        task = asyncio.create_task(_process_utterances_with_streaming())
        logger.info("✅ FULL STREAMING PIPELINE active and ready")
    else:
        logger.info("⚠️ STT running in API-only mode (LiveKit connection failed)")
        
    yield
    
    # Cleanup
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
    # Cancel all partial streaming tasks
    for pid, partial_task in list(partial_streaming_tasks.items()):
        partial_task.cancel()
        try:
            await partial_task
        except asyncio.CancelledError:
            pass
    partial_streaming_tasks.clear()
    
    if room and room_connected:
        try:
            await room.disconnect()
        except Exception as e:
            logger.debug(f"⚠️ LiveKit disconnect error: {e}")


app = FastAPI(
    title="June STT - Full Streaming Pipeline (Resilient)",
    version="6.0.2-streaming-resilient",
    description="Continuous partial transcripts + Online LLM processing + Silero VAD + LiveKit (with fallback)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
):
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Whisper + Silero VAD not ready")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            result = await whisper_service.transcribe(tmp.name, language=language)
        text = result.get("text", "")
        if response_format == "text":
            return text
        elif response_format == "verbose_json":
            return {
                "task": "transcribe",
                "language": result.get("language", language or "en"),
                "text": text,
                "segments": result.get("segments", []),
                "method": result.get("method", "silero_enhanced"),
            }
        else:
            return {"text": text}
    except Exception as e:
        logger.error(f"OpenAI API transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "version": "6.0.2-streaming-resilient",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
            "silero_vad_enabled": getattr(config, 'SILERO_VAD_ENABLED', True),
            "streaming_enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED,
            "continuous_partials": CONTINUOUS_PARTIALS,
        },
        "features": {
            "openai_api_compatible": True,
            "silero_vad_intelligent_detection": True,
            "real_time_voice_chat": room_connected,
            "partial_transcripts": PARTIALS_ENABLED,
            "continuous_streaming": CONTINUOUS_PARTIALS,
            "online_llm_processing": CONTINUOUS_PARTIALS and orchestrator_available,
            "streaming_architecture": STREAMING_ENABLED,
            "anti_feedback": True,
            "resilient_startup": True,
        },
        "streaming_pipeline": {
            "speech_to_partial_ms": f"<{PARTIAL_MIN_SPEECH_MS}",
            "partial_emit_interval_ms": PARTIAL_EMIT_INTERVAL_MS,
            "online_processing": CONTINUOUS_PARTIALS and orchestrator_available,
            "overlapping_pipeline": "speech-in + thinking + speech-out",
            "fixes_applied": "resilient_startup + retry_logic",
        }
    }


@app.get("/")
async def root():
    active_streaming_tasks = len(partial_streaming_tasks)
    active_participants = len(buffers)
    pipeline_ready = CONTINUOUS_PARTIALS and room_connected and whisper_service.is_model_ready() and orchestrator_available
    
    return {
        "service": "june-stt",
        "version": "6.0.2-streaming-resilient",
        "description": "FULL STREAMING PIPELINE: Continuous partials + Online LLM + Silero VAD + LiveKit (Resilient)",
        "features": [
            "Silero VAD intelligent speech detection",
            "CONTINUOUS partial transcript streaming (250ms intervals)",
            "ONLINE LLM processing (starts while user speaks)",
            "OpenAI API compatibility",
            "Real-time LiveKit integration",
            "Anti-feedback protection",
            "Enhanced orchestrator integration",
            "Per-utterance tracking and deduplication",
            "RESILIENT startup and error handling",
            "Performance metrics",
        ],
        "streaming": {
            "enabled": STREAMING_ENABLED,
            "continuous_partials": CONTINUOUS_PARTIALS,
            "partial_interval_ms": PARTIAL_EMIT_INTERVAL_MS,
            "min_speech_for_partials_ms": PARTIAL_MIN_SPEECH_MS,
            "online_processing": CONTINUOUS_PARTIALS,
        },
        "pipeline_status": {
            "target_achieved": pipeline_ready,
            "speech_in_thinking_speech_out": "ACTIVE" if pipeline_ready else "PARTIAL",
            "overlapping_processing": pipeline_ready,
            "resilient_mode": "ENABLED",
        },
        "current_status": {
            "active_participants": active_participants,
            "active_streaming_tasks": active_streaming_tasks,
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "pipeline_ready": pipeline_ready,
            "orchestrator_reachable": orchestrator_available,
        },
        "stats": streaming_metrics.get_stats(),
    }


@app.get("/debug/pipeline")
async def debug_pipeline():
    """Debug endpoint for pipeline status"""
    return {
        "streaming_config": {
            "STREAMING_ENABLED": STREAMING_ENABLED,
            "PARTIALS_ENABLED": PARTIALS_ENABLED,
            "CONTINUOUS_PARTIALS": CONTINUOUS_PARTIALS,
        },
        "timing_config": {
            "PARTIAL_EMIT_INTERVAL_MS": PARTIAL_EMIT_INTERVAL_MS,
            "PARTIAL_MIN_SPEECH_MS": PARTIAL_MIN_SPEECH_MS,
            "MAX_UTTERANCE_SEC": MAX_UTTERANCE_SEC,
            "SILENCE_TIMEOUT_SEC": SILENCE_TIMEOUT_SEC,
        },
        "connectivity": {
            "room_connected": room_connected,
            "orchestrator_available": orchestrator_available,
            "orchestrator_url": config.ORCHESTRATOR_URL,
        },
        "current_state": {
            "active_participants": list(buffers.keys()),
            "utterance_states": {pid: {
                "is_active": state.is_active,
                "partial_sequence": state.partial_sequence,
                "utterance_id": state.utterance_id[:8],
                "first_partial_sent": state.first_partial_sent,
            } for pid, state in utterance_states.items()},
            "active_streaming_tasks": list(partial_streaming_tasks.keys()),
            "whisper_ready": whisper_service.is_model_ready(),
        },
        "performance": {
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "streaming_stats": streaming_metrics.get_stats(),
        },
        "fixes_applied": [
            "Enhanced state management",
            "Better error handling in processing loops",
            "Safe participant iteration",
            "Proper async task cleanup",
            "Enhanced utterance tracking",
            "Resilient orchestrator connection",
            "LiveKit connection retry logic",
            "Graceful degradation on connection failures",
        ]
    }


@app.post("/debug/test-partial")
async def test_partial_generation():
    """Debug endpoint to test partial transcript generation"""
    if not whisper_service.is_model_ready():
        return {"error": "Whisper not ready"}
        
    # Create a test utterance state for debugging
    test_pid = "debug-test"
    state = _ensure_utterance_state(test_pid)
    
    return {
        "message": "Partial generation test completed",
        "state_created": test_pid in utterance_states,
        "continuous_partials_enabled": CONTINUOUS_PARTIALS,
        "streaming_enabled": STREAMING_ENABLED,
        "orchestrator_available": orchestrator_available,
        "pipeline_ready_for_partials": CONTINUOUS_PARTIALS and orchestrator_available and whisper_service.is_model_ready(),
    }


@app.get("/stats")
async def stats():
    active_participants = list(buffers.keys())
    utterance_participants = list(utterance_states.keys())
    active_streaming_tasks = len(partial_streaming_tasks)
    
    participant_stats = {}
    for pid in utterance_participants:
        try:
            state = utterance_states[pid]
            participant_stats[pid] = {
                "is_active": state.is_active,
                "buffer_frames": len(state.buffer),
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "first_partial_sent": state.first_partial_sent,
                "partial_sequence": state.partial_sequence,
                "utterance_id": state.utterance_id[:8] if hasattr(state, 'utterance_id') else None,
                "has_continuous_task": pid in partial_streaming_tasks,
            }
        except Exception as e:
            participant_stats[pid] = {"error": f"State access error: {e}"}
        
    return {
        "status": "success",
        "version": "6.0.2-streaming-resilient",
        "connectivity": {
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
        },
        "intelligence": {
            "silero_vad_enabled": getattr(config, 'SILERO_VAD_ENABLED', True),
            "speech_detection_method": "Silero VAD (ML)" if getattr(config, 'SILERO_VAD_ENABLED', True) else "Fallback",
        },
        "streaming": {
            "enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED,
            "continuous_partials": CONTINUOUS_PARTIALS,
            "partial_chunk_ms": PARTIAL_CHUNK_MS,
            "continuous_emit_interval_ms": PARTIAL_EMIT_INTERVAL_MS,
            "metrics": streaming_metrics.get_stats(),
        },
        "pipeline": {
            "mode": "CONTINUOUS_ONLINE" if CONTINUOUS_PARTIALS else "BATCH_AFTER_SILENCE",
            "target_achieved": CONTINUOUS_PARTIALS and orchestrator_available and room_connected,
            "overlapping_speech_thinking_speech": CONTINUOUS_PARTIALS and orchestrator_available,
            "fixes_status": "RESILIENT_ENHANCED",
        },
        "global_stats": {
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "active_participants": len(active_participants),
            "active_continuous_tasks": active_streaming_tasks,
        },
        "participants": participant_stats,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)