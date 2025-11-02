#!/usr/bin/env python3
"""
June STT Service - Clean and Optimized
Real-time Speech-to-Text with LiveKit integration and Silero VAD
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

# Feature flags
STREAMING_ENABLED = getattr(config, "STT_STREAMING_ENABLED", True)
PARTIALS_ENABLED = getattr(config, "STT_PARTIALS_ENABLED", True)
CONTINUOUS_PARTIALS = os.getenv("STT_CONTINUOUS_PARTIALS", "true").lower() == "true"

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
orchestrator_available: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, 'UtteranceState'] = {}
partial_streamers: Dict[str, PartialTranscriptStreamer] = {}
partial_streaming_tasks: Dict[str, asyncio.Task] = {}
processed_utterances = 0
partial_transcripts_sent = 0

# Constants
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 8.0
MIN_UTTERANCE_SEC = 0.3
PROCESS_SLEEP_SEC = 0.03
SILENCE_TIMEOUT_SEC = 0.8
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}
PARTIAL_CHUNK_MS = 150
PARTIAL_MIN_SPEECH_MS = 200
PARTIAL_EMIT_INTERVAL_MS = 200
MAX_PARTIAL_LENGTH = 120

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0
        self.first_partial_sent = False
        self.last_partial_sent_at: Optional[datetime] = None
        self.partial_sequence = 0
        self.utterance_id = str(uuid.uuid4())

def _ensure_utterance_state(pid: str) -> UtteranceState:
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
    return utterance_states[pid]

def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=800)
    return buffers[pid]

def _ensure_partial_streamer(pid: str) -> PartialTranscriptStreamer:
    if pid not in partial_streamers:
        partial_streamers[pid] = PartialTranscriptStreamer(
            chunk_duration_ms=PARTIAL_CHUNK_MS,
            min_speech_ms=PARTIAL_MIN_SPEECH_MS,
        )
    return partial_streamers[pid]

def _reset_utterance_state(state: UtteranceState):
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_audio_at = None
    state.total_samples = 0
    state.first_partial_sent = False
    state.last_partial_sent_at = None
    state.partial_sequence = 0
    state.utterance_id = str(uuid.uuid4())

async def _check_orchestrator_health() -> bool:
    if not config.ORCHESTRATOR_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{config.ORCHESTRATOR_URL}/healthz")
            return r.status_code == 200
    except Exception:
        return False

async def _notify_orchestrator(user_id: str, text: str, language: Optional[str], partial: bool = False, 
                              utterance_id: Optional[str] = None, partial_sequence: int = 0):
    global orchestrator_available, partial_transcripts_sent
    
    if not config.ORCHESTRATOR_URL:
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
    
    if partial:
        payload.update({
            "utterance_id": utterance_id,
            "partial_sequence": partial_sequence,
            "is_streaming": True,
        })

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.post(f"{config.ORCHESTRATOR_URL}/api/webhooks/stt", json=payload)
            orchestrator_available = r.status_code in (200, 429)
            if partial:
                partial_transcripts_sent += 1
    except Exception:
        orchestrator_available = False

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
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32), sr

def _resample_to_16k_mono(pcm: np.ndarray, sr: int) -> np.ndarray:
    if sr == SAMPLE_RATE:
        return pcm
    gcd = np.gcd(sr, SAMPLE_RATE)
    up = SAMPLE_RATE // gcd
    down = sr // gcd
    out = signal.resample_poly(pcm, up, down).astype(np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)

async def _continuous_partial_processor(pid: str, state: UtteranceState, streamer: PartialTranscriptStreamer):
    if not CONTINUOUS_PARTIALS or not whisper_service.is_model_ready():
        return
        
    utterance_id = state.utterance_id
    
    try:
        while state.is_active:
            try:
                if state.started_at:
                    duration_ms = (datetime.utcnow() - state.started_at).total_seconds() * 1000
                    
                    first_partial_threshold = PARTIAL_MIN_SPEECH_MS
                    if not state.first_partial_sent:
                        first_partial_threshold = 150
                    
                    if duration_ms >= first_partial_threshold:
                        now = datetime.utcnow()
                        emit_interval = PARTIAL_EMIT_INTERVAL_MS
                        
                        if state.first_partial_sent:
                            emit_interval = max(150, PARTIAL_EMIT_INTERVAL_MS - 50)
                        
                        if (not state.last_partial_sent_at or 
                            (now - state.last_partial_sent_at).total_seconds() * 1000 >= emit_interval):
                            
                            if len(state.buffer) > 0:
                                window_duration = 1.2 if state.first_partial_sent else 0.8
                                recent_frames = list(state.buffer)[-int(window_duration * SAMPLE_RATE / 320):]
                                
                                if recent_frames:
                                    try:
                                        partial_audio = np.concatenate(recent_frames, axis=0)
                                        min_samples = int(first_partial_threshold / 1000 * SAMPLE_RATE)
                                        
                                        if len(partial_audio) >= min_samples:
                                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                                                sf.write(tmp.name, partial_audio, SAMPLE_RATE, subtype='PCM_16')
                                                res = await whisper_service.transcribe(tmp.name, language=None)
                                            
                                            partial_text = res.get("text", "").strip()
                                            min_partial_length = 2 if not state.first_partial_sent else 3
                                            
                                            if (partial_text and len(partial_text) > min_partial_length and 
                                                len(partial_text) <= MAX_PARTIAL_LENGTH and
                                                streamer.should_emit_partial(partial_text)):
                                                
                                                state.partial_sequence += 1
                                                
                                                await _notify_orchestrator(
                                                    pid, partial_text, res.get("language"), 
                                                    partial=True, utterance_id=utterance_id,
                                                    partial_sequence=state.partial_sequence
                                                )
                                                
                                                streamer.update_partial_text(partial_text)
                                                state.last_partial_sent_at = now
                                                state.first_partial_sent = True
                                                streaming_metrics.record_partial(0)
                                    
                                    except Exception:
                                        pass
                
                sleep_duration = PARTIAL_EMIT_INTERVAL_MS / 1000
                if not state.first_partial_sent:
                    sleep_duration = 0.1
                
                await asyncio.sleep(sleep_duration)
                
            except Exception:
                await asyncio.sleep(0.3)
            
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        if pid in partial_streaming_tasks:
            del partial_streaming_tasks[pid]

async def _transcribe_utterance_with_silero(pid: str, audio: np.ndarray, utterance_id: str):
    global processed_utterances
    if not whisper_service.is_model_ready():
        return
        
    try:
        if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
            return
            
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None)
            
        text = res.get("text", "").strip()
        
        if text and len(text) > 1:
            filtered_words = {"you", "you.", "uh", "um", "mm", "hmm", "yeah", "mhm", "ah", "oh"}
            if text.lower() not in filtered_words:
                await _notify_orchestrator(pid, text, res.get("language"), partial=False)
                processed_utterances += 1
                streaming_metrics.record_final()
            
    except Exception:
        pass

async def _process_utterances_with_streaming():
    global processed_utterances, orchestrator_available
    
    last_health_check = time.time()
    health_check_interval = 20.0
    
    while True:
        try:
            current_time = time.time()
            if current_time - last_health_check > health_check_interval:
                orchestrator_available = await _check_orchestrator_health()
                last_health_check = current_time
            
            participants_to_process = list(buffers.keys())
            
            for pid in participants_to_process:
                try:
                    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
                        continue
                    
                    state = _ensure_utterance_state(pid)
                    buf = _ensure_buffer(pid)
                    streamer = _ensure_partial_streamer(pid) if STREAMING_ENABLED else None
                    
                    while buf:
                        try:
                            frame = buf.popleft()
                            now = datetime.utcnow()
                            
                            if not state.is_active:
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
                                    
                                if (CONTINUOUS_PARTIALS and STREAMING_ENABLED and 
                                    pid not in partial_streaming_tasks):
                                    task = asyncio.create_task(_continuous_partial_processor(pid, state, streamer))
                                    partial_streaming_tasks[pid] = task
                                    
                            else:
                                state.buffer.append(frame)
                                state.total_samples += len(frame)
                                state.last_audio_at = now
                                
                                if STREAMING_ENABLED and streamer and not CONTINUOUS_PARTIALS:
                                    streamer.add_audio_chunk(frame)
                                    
                                duration = (now - state.started_at).total_seconds()
                                silence_duration = (now - state.last_audio_at).total_seconds()
                                
                                should_end = (
                                    duration >= MAX_UTTERANCE_SEC or
                                    (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)
                                )
                                
                                if should_end:
                                    if pid in partial_streaming_tasks:
                                        partial_streaming_tasks[pid].cancel()
                                        try:
                                            await partial_streaming_tasks[pid]
                                        except asyncio.CancelledError:
                                            pass
                                        del partial_streaming_tasks[pid]
                                    
                                    if len(state.buffer) > 0:
                                        utterance_audio = np.concatenate(list(state.buffer), axis=0)
                                        utterance_id = state.utterance_id
                                        await _transcribe_utterance_with_silero(pid, utterance_audio, utterance_id)
                                    
                                    _reset_utterance_state(state)
                                    if streamer:
                                        streamer.reset()
                                    
                        except Exception:
                            continue
                            
                except Exception:
                    continue
                    
        except Exception:
            pass
            
        await asyncio.sleep(PROCESS_SLEEP_SEC)

async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
        return
    try:
        pcm, sr = _frame_to_float32_mono(frame)
        pcm16k = _resample_to_16k_mono(pcm, sr)
        _ensure_buffer(pid).append(pcm16k)
    except Exception:
        pass

def setup_room_callbacks(room: rtc.Room):
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"Participant joined: {p.identity}")
        if p.identity not in EXCLUDE_PARTICIPANTS:
            _ensure_utterance_state(p.identity)
            _ensure_buffer(p.identity)

    @room.on("participant_disconnected")
    def _p_leave(p):
        pid = p.identity
        if pid in buffers:
            del buffers[pid]
        if pid in utterance_states:
            del utterance_states[pid]
        if pid in partial_streamers:
            del partial_streamers[pid]
        if pid in partial_streaming_tasks:
            partial_streaming_tasks[pid].cancel()
            del partial_streaming_tasks[pid]

    @room.on("track_subscribed")
    def _track_sub(track: rtc.Track, pub, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        pid = participant.identity or participant.sid
        if pid in EXCLUDE_PARTICIPANTS:
            return
        
        _ensure_utterance_state(pid)
        _ensure_buffer(pid)
        
        stream = rtc.AudioStream(track)
        async def consume():
            async for event in stream:
                await _on_audio_frame(pid, event.frame)
        asyncio.create_task(consume())

async def join_livekit_room():
    global room, room_connected
    if not config.LIVEKIT_ENABLED:
        logger.info("LiveKit disabled")
        return
        
    try:
        room = rtc.Room()
        setup_room_callbacks(room)
        await connect_room_as_subscriber(room, "june-stt")
        room_connected = True
        logger.info("STT connected to LiveKit")
        
        global orchestrator_available
        orchestrator_available = await _check_orchestrator_health()
        
    except Exception as e:
        logger.error(f"LiveKit connection failed: {e}")
        room_connected = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("June STT Service starting")
    
    try:
        await whisper_service.initialize()
        logger.info("Whisper + Silero VAD ready")
    except Exception as e:
        logger.error(f"Service init failed: {e}")
        raise
        
    await join_livekit_room()
    
    task = None
    if room_connected:
        task = asyncio.create_task(_process_utterances_with_streaming())
        logger.info("STT processing active")
    else:
        logger.info("STT running in API-only mode")
        
    yield
    
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
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
        except Exception:
            pass

app = FastAPI(
    title="June STT",
    version="7.1.0-clean",
    description="Real-time Speech-to-Text with LiveKit and Silero VAD",
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
        raise HTTPException(status_code=503, detail="Whisper not ready")
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
                "method": result.get("method", "enhanced"),
            }
        else:
            return {"text": text}
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "version": "7.1.0-clean",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
            "streaming_enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED,
            "continuous_partials": CONTINUOUS_PARTIALS,
        }
    }

@app.get("/")
async def root():
    return {
        "service": "june-stt",
        "version": "7.1.0-clean",
        "description": "Real-time Speech-to-Text with Silero VAD and LiveKit",
        "status": {
            "active_participants": len(buffers),
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "orchestrator_reachable": orchestrator_available,
        },
        "stats": streaming_metrics.get_stats(),
    }

@app.get("/stats")
async def stats():
    return {
        "status": "success",
        "version": "7.1.0-clean",
        "connectivity": {
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
        },
        "streaming": {
            "enabled": STREAMING_ENABLED,
            "partials_enabled": PARTIALS_ENABLED,
            "continuous_partials": CONTINUOUS_PARTIALS,
            "metrics": streaming_metrics.get_stats(),
        },
        "global_stats": {
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "active_participants": len(buffers),
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)