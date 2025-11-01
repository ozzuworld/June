#!/usr/bin/env python3
"""
June STT Enhanced - Silero VAD + LiveKit Integration + STREAMING
Intelligent speech detection + Partial transcript streaming for lower latency
OpenAI API compatible + Real-time voice chat capabilities
"""
import asyncio
import logging
import uuid
import tempfile
import soundfile as sf
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

# Feature flags for streaming
STREAMING_ENABLED = config.get("STT_STREAMING_ENABLED", True)
PARTIALS_ENABLED = config.get("STT_PARTIALS_ENABLED", True)

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, dict] = {}
partial_streamers: Dict[str, PartialTranscriptStreamer] = {}
processed_utterances = 0

# Simplified constants (Silero VAD handles complexity)
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 8.0
MIN_UTTERANCE_SEC = 0.5
PROCESS_SLEEP_SEC = 0.1
SILENCE_TIMEOUT_SEC = 1.0
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

# STREAMING: Partial processing parameters
PARTIAL_CHUNK_MS = 200  # Process partials every 200ms
PARTIAL_MIN_SPEECH_MS = 500  # Minimum speech before emitting partials

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0
        self.first_partial_sent = False  # STREAMING: Track first partial

# Helper functions (enhanced for streaming)
def _ensure_utterance_state(pid: str) -> UtteranceState:
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
    return utterance_states[pid]

def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=400)
    return buffers[pid]

def _ensure_partial_streamer(pid: str) -> PartialTranscriptStreamer:
    """STREAMING: Ensure partial streamer exists for participant"""
    if pid not in partial_streamers:
        partial_streamers[pid] = PartialTranscriptStreamer(
            chunk_duration_ms=PARTIAL_CHUNK_MS,
            min_speech_ms=PARTIAL_MIN_SPEECH_MS
        )
    return partial_streamers[pid]

def _reset_utterance_state(state: UtteranceState):
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_audio_at = None
    state.total_samples = 0
    state.first_partial_sent = False

async def _notify_orchestrator(user_id: str, text: str, language: Optional[str], partial: bool = False):
    """Enhanced orchestrator notification with partial support"""
    if not config.ORCHESTRATOR_URL:
        return

    payload = {
        "transcript_id": str(uuid.uuid4()),
        "user_id": user_id,
        "participant": user_id,
        "event": "partial_transcript" if partial else "transcript",  # STREAMING: New event type
        "text": text,
        "language": language,
        "timestamp": datetime.utcnow().isoformat(),
        "room_name": "ozzu-main",
        "partial": partial,  # STREAMING: Flag for partial transcripts
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{config.ORCHESTRATOR_URL}/api/webhooks/stt",
                json=payload,
            )
            if r.status_code == 429:
                logger.info(f"🛱️ Rate limited by orchestrator: {r.text}")
            elif r.status_code != 200:
                logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
            else:
                event_type = "partial" if partial else "final"
                logger.info(f"📤 Sent {event_type} transcript to orchestrator: '{text}'")
    except Exception as e:
        logger.warning(f"Orchestrator notify error: {e}")

# Audio processing (unchanged)
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

async def _process_partial_transcript(pid: str, audio: np.ndarray, streamer: PartialTranscriptStreamer):
    """STREAMING: Process partial transcript for real-time feedback"""
    if not PARTIALS_ENABLED or not whisper_service.is_model_ready():
        return
        
    try:
        start_time = time.time()
        
        # Quick transcription for partial
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None, quick=True)
            
        processing_time = (time.time() - start_time) * 1000
        text = res.get("text", "").strip()
        
        if text and streamer.should_emit_partial(text):
            logger.info(f"⚡ PARTIAL[{pid}] ({processing_time:.0f}ms): {text}")
            streamer.update_partial_text(text)
            
            # Send partial to orchestrator
            await _notify_orchestrator(pid, text, res.get("language"), partial=True)
            
            # Update metrics
            streaming_metrics.record_partial(processing_time)
            
    except Exception as e:
        logger.debug(f"⚠️ Partial transcription error for {pid}: {e}")

async def _transcribe_utterance_with_silero(pid: str, audio: np.ndarray):
    """Enhanced transcription with Silero VAD + streaming support"""
    global processed_utterances
    
    if not whisper_service.is_model_ready():
        logger.warning("⚠️ Whisper model not ready")
        return

    try:
        duration = len(audio) / SAMPLE_RATE
        
        # Silero VAD pre-filter
        if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
            logger.debug(f"🔇 Silero VAD filtered out non-speech for {pid} ({duration:.2f}s)")
            return
        
        logger.info(f"🎯 Silero VAD confirmed speech for {pid}: {duration:.2f}s")
        
        # Process with Whisper (final transcription)
        start_time = time.time()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None)
        
        processing_time = (time.time() - start_time) * 1000
        text = res.get("text", "").strip()
        method = res.get("method", "silero_enhanced")

        if text and len(text) > 2:
            if text.lower() not in ["you", "you.", "uh", "um", "mm"]:
                logger.info(f"✅ FINAL[{pid}] via {method} ({processing_time:.0f}ms): {text}")
                await _notify_orchestrator(pid, text, res.get("language"), partial=False)
                processed_utterances += 1
                streaming_metrics.record_final()
            else:
                logger.debug(f"😫 Filtered false positive: '{text}'")
        else:
            logger.debug(f"🔇 Empty transcription result")

    except Exception as e:
        logger.error(f"❌ Transcription error for {pid}: {e}")

async def _process_utterances_with_streaming():
    """Enhanced utterance processing with streaming partial support"""
    global processed_utterances
    
    logger.info(f"🚀 Starting Silero VAD-enhanced STT processing")
    if STREAMING_ENABLED and PARTIALS_ENABLED:
        logger.info(f"⚡ STREAMING MODE: Partial transcripts every {PARTIAL_CHUNK_MS}ms")
    logger.info(f"🎯 Intelligent speech detection replaces custom thresholds")

    while True:
        try:
            for pid in list(buffers.keys()):
                if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
                    continue

                state = _ensure_utterance_state(pid)
                buf = _ensure_buffer(pid)
                streamer = _ensure_partial_streamer(pid) if STREAMING_ENABLED else None
                
                while buf:
                    frame = buf.popleft()
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
                        
                        if streamer:
                            streamer.reset()
                            
                        logger.debug(f"🎬 Started utterance capture for {pid}")
                        
                    else:
                        # Continue existing utterance
                        state.buffer.append(frame)
                        state.total_samples += len(frame)
                        state.last_audio_at = now
                        
                        # STREAMING: Process partial transcripts
                        if STREAMING_ENABLED and streamer and not state.first_partial_sent:
                            streamer.add_audio_chunk(frame)
                            
                            duration = (now - state.started_at).total_seconds()
                            if duration >= (PARTIAL_MIN_SPEECH_MS / 1000):
                                partial_audio = streamer.get_partial_audio()
                                if partial_audio is not None:
                                    # Process partial in background
                                    asyncio.create_task(_process_partial_transcript(pid, partial_audio, streamer))
                                    state.first_partial_sent = True
                        
                        # Check for end conditions
                        duration = (now - state.started_at).total_seconds()
                        silence_duration = (now - state.last_audio_at).total_seconds()
                        
                        should_end = (
                            duration >= MAX_UTTERANCE_SEC or
                            (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)
                        )
                        
                        if should_end:
                            utterance_audio = np.concatenate(list(state.buffer), axis=0)
                            utterance_duration = len(utterance_audio) / SAMPLE_RATE
                            
                            logger.info(f"🎬 Ending utterance for {pid}: {utterance_duration:.2f}s")
                            
                            # Final transcription (high quality)
                            await _transcribe_utterance_with_silero(pid, utterance_audio)
                            _reset_utterance_state(state)
                            
                            # Reset partial streamer
                            if streamer:
                                streamer.reset()

        except Exception as e:
            logger.warning(f"❌ Utterance processing error: {e}")

        await asyncio.sleep(PROCESS_SLEEP_SEC)

async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
        return
    
    pcm, sr = _frame_to_float32_mono(frame)
    pcm16k = _resample_to_16k_mono(pcm, sr)
    _ensure_buffer(pid).append(pcm16k)

# LiveKit room setup (unchanged)
def setup_room_callbacks(room: rtc.Room):
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"👤 Participant joined: {p.identity}")
        if p.identity in EXCLUDE_PARTICIPANTS:
            logger.info(f"😫 Participant {p.identity} is EXCLUDED from STT processing")

    @room.on("participant_disconnected")
    def _p_leave(p):
        logger.info(f"👋 Participant left: {p.identity}")
        if p.identity in buffers:
            del buffers[p.identity]
        if p.identity in utterance_states:
            del utterance_states[p.identity]
        if p.identity in partial_streamers:
            del partial_streamers[p.identity]

    @room.on("track_subscribed")
    def _track_sub(track: rtc.Track, pub, participant):
        logger.info(f"🎵 TRACK SUBSCRIBED: kind={track.kind}, participant={participant.identity}")

        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        pid = participant.identity or participant.sid
        if pid in EXCLUDE_PARTICIPANTS:
            logger.info(f"😫 EXCLUDED participant {pid} - not processing audio")
            return
            
        logger.info(f"✅ Subscribed to audio of {pid}")
        stream = rtc.AudioStream(track)

        async def consume():
            logger.info(f"🎧 Starting audio consumption for {pid}")
            async for event in stream:
                await _on_audio_frame(pid, event.frame)

        asyncio.create_task(consume())

async def join_livekit_room():
    global room, room_connected
    
    if not config.LIVEKIT_ENABLED:
        logger.info("LiveKit disabled, skipping connection")
        return

    logger.info("Connecting STT to LiveKit via orchestrator token")
    room = rtc.Room()
    setup_room_callbacks(room)
    await connect_room_as_subscriber(room, "june-stt")
    room_connected = True
    logger.info("STT connected and listening for audio frames")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 June STT Enhanced - Silero VAD + LiveKit Integration + STREAMING")
    logger.info(f"Features: OpenAI API Compatible + Intelligent Speech Detection + Partial Transcripts")
    logger.info(f"⚡ Streaming: {STREAMING_ENABLED}, Partials: {PARTIALS_ENABLED}")

    try:
        await whisper_service.initialize()
        logger.info("✅ Enhanced Whisper + Silero VAD + Streaming service ready")
    except Exception as e:
        logger.error(f"Enhanced service init failed: {e}")

    await join_livekit_room()
    
    if room_connected:
        # Use streaming-enhanced processing
        task = asyncio.create_task(_process_utterances_with_streaming())
    
    yield
    
    if room_connected and 'task' in locals():
        task.cancel()
    if room and room_connected:
        await room.disconnect()

# FastAPI application
app = FastAPI(
    title="June STT with Silero VAD + Streaming",
    version="5.0.0-streaming",
    description="Intelligent speech detection + Partial transcripts + OpenAI API + LiveKit real-time voice chat",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI-compatible endpoints (unchanged)
@app.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
):
    """OpenAI-compatible transcription endpoint with Silero VAD"""
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
                "method": result.get("method", "silero_enhanced")
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
        "version": "5.0.0-streaming",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "livekit_connected": room_connected,
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "streaming_enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED
        },
        "features": {
            "openai_api_compatible": True,
            "silero_vad_intelligent_detection": True,
            "real_time_voice_chat": config.LIVEKIT_ENABLED,
            "partial_transcripts": PARTIALS_ENABLED,
            "streaming_architecture": STREAMING_ENABLED,
            "anti_feedback": True
        }
    }

@app.get("/")
async def root():
    return {
        "service": "june-stt",
        "version": "5.0.0-streaming", 
        "description": "Silero VAD + Streaming partial transcripts + OpenAI API + LiveKit",
        "features": [
            "Silero VAD intelligent speech detection",
            "Streaming partial transcripts (200ms intervals)",
            "OpenAI API compatibility",
            "Real-time LiveKit integration", 
            "Anti-feedback protection",
            "Orchestrator integration",
            "Performance metrics"
        ],
        "streaming": {
            "enabled": STREAMING_ENABLED,
            "partial_interval_ms": PARTIAL_CHUNK_MS,
            "min_speech_for_partials_ms": PARTIAL_MIN_SPEECH_MS
        },
        "stats": {
            "processed_utterances": processed_utterances,
            **streaming_metrics.get_stats()
        }
    }

@app.get("/stats")
async def stats():
    """Enhanced stats with streaming metrics"""
    active_participants = list(buffers.keys())
    utterance_participants = list(utterance_states.keys())
    
    participant_stats = {}
    for pid in utterance_participants:
        state = utterance_states[pid]
        participant_stats[pid] = {
            "is_active": state.is_active,
            "buffer_frames": len(state.buffer),
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "first_partial_sent": state.first_partial_sent
        }
    
    return {
        "status": "success",
        "intelligence": {
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "speech_detection_method": "Silero VAD (ML)" if config.SILERO_VAD_ENABLED else "Fallback"
        },
        "streaming": {
            "enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED,
            "partial_chunk_ms": PARTIAL_CHUNK_MS,
            "metrics": streaming_metrics.get_stats()
        },
        "global_stats": {
            "processed_utterances": processed_utterances,
            "active_participants": len(active_participants)
        },
        "participants": participant_stats
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)