#!/usr/bin/env python3
"""
June STT Service - WhisperX Native Implementation
Real-time Speech-to-Text with WhisperX built-in VAD
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
from streaming_utils import streaming_metrics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt")

# Feature flags
STREAMING_ENABLED = getattr(config, "STT_STREAMING_ENABLED", True)
PARTIALS_ENABLED = getattr(config, "STT_PARTIALS_ENABLED", True)

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
orchestrator_available: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, 'UtteranceState'] = {}
processed_utterances = 0
partial_transcripts_sent = 0

# Constants
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = float(os.getenv("MAX_UTTERANCE_SEC", "8.0"))
MIN_UTTERANCE_SEC = float(os.getenv("MIN_UTTERANCE_SEC", "0.4"))
SILENCE_TIMEOUT_SEC = float(os.getenv("SILENCE_TIMEOUT_SEC", "1.2"))
PROCESS_SLEEP_SEC = 0.05
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

logger.info(f"⚡ Timing config: MAX={MAX_UTTERANCE_SEC}s, MIN={MIN_UTTERANCE_SEC}s, SILENCE={SILENCE_TIMEOUT_SEC}s")


class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0
        self.utterance_id = str(uuid.uuid4())


def _ensure_utterance_state(pid: str) -> 'UtteranceState':
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
    return utterance_states[pid]


def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=800)
    return buffers[pid]


def _reset_utterance_state(state: UtteranceState):
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_audio_at = None
    state.total_samples = 0
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


async def _notify_orchestrator(user_id: str, text: str, language: Optional[str], partial: bool = False):
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

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.post(f"{config.ORCHESTRATOR_URL}/api/webhooks/stt", json=payload)
            orchestrator_available = r.status_code in (200, 429)
            if partial:
                partial_transcripts_sent += 1
    except Exception:
        orchestrator_available = False


_first_frame_seen = set()


def _frame_to_float32_mono(frame: rtc.AudioFrame):
    """Convert LiveKit audio frame to float32 mono"""
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
    """Resample audio to 16kHz"""
    if sr == SAMPLE_RATE:
        return pcm
    gcd = np.gcd(sr, SAMPLE_RATE)
    up = SAMPLE_RATE // gcd
    down = sr // gcd
    out = signal.resample_poly(pcm, up, down).astype(np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


async def _transcribe_utterance(pid: str, audio: np.ndarray, utterance_id: str):
    """Transcribe complete utterance using WhisperX"""
    global processed_utterances
    
    if not whisper_service.is_model_ready():
        return
        
    try:
        logger.info(f"[FINAL] transcribe pid={pid} samples={len(audio)}")
        
        # Simple pre-check (WhisperX VAD will do real detection)
        if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
            logger.info(f"[FINAL] skipped (silence) pid={pid}")
            return
            
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            logger.info(f"[FINAL] calling WhisperX pid={pid}")
            
            # WhisperX will handle VAD internally
            res = await whisper_service.transcribe(tmp.name, language=None)
            
        # Check if WhisperX VAD filtered it
        if res.get("filtered"):
            logger.info(f"[FINAL] filtered by WhisperX: {res.get('filtered')} pid={pid}")
            return
        
        text = res.get("text", "").strip()
        logger.info(f"[FINAL] result pid={pid} len={len(text)} text='{text[:80]}'")
        
        if text and len(text) > 1:
            # Filter noise words
            filtered_words = {"you", "you.", "uh", "um", "mm", "hmm", "yeah", "mhm", "ah", "oh"}
            if text.lower() not in filtered_words:
                await _notify_orchestrator(pid, text, res.get("language"), partial=False)
                processed_utterances += 1
                streaming_metrics.record_final()
            
    except Exception as e:
        logger.error(f"[FINAL] transcription error pid={pid}: {e}", exc_info=True)


async def _process_utterances():
    """Process audio utterances from buffers"""
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
                    if pid in EXCLUDE_PARTICIPANTS:
                        continue
                    
                    state = _ensure_utterance_state(pid)
                    buf = _ensure_buffer(pid)
                    
                    while buf:
                        try:
                            frame = buf.popleft()
                            now = datetime.utcnow()
                            
                            if not state.is_active:
                                logger.info(f"[UTT] start pid={pid}")
                                state.is_active = True
                                state.started_at = now
                                state.last_audio_at = now
                                state.buffer.clear()
                                state.buffer.append(frame)
                                state.total_samples = len(frame)
                                state.utterance_id = str(uuid.uuid4())
                                    
                            else:
                                state.buffer.append(frame)
                                state.total_samples += len(frame)
                                state.last_audio_at = now
                                
                                duration = (now - state.started_at).total_seconds()
                                silence_duration = (now - state.last_audio_at).total_seconds()
                                
                                should_end = (
                                    duration >= MAX_UTTERANCE_SEC or
                                    (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)
                                )
                                
                                if should_end:
                                    logger.info(f"[UTT] end pid={pid} dur={duration:.2f}s silence={silence_duration:.2f}s samples={state.total_samples}")
                                    
                                    if len(state.buffer) > 0:
                                        utterance_audio = np.concatenate(list(state.buffer), axis=0)
                                        utterance_id = state.utterance_id
                                        await _transcribe_utterance(pid, utterance_audio, utterance_id)
                                    
                                    _reset_utterance_state(state)
                                    
                        except Exception as e:
                            logger.error(f"[UTT] frame processing error pid={pid}: {e}")
                            continue
                            
                except Exception as e:
                    logger.error(f"[UTT] participant processing error pid={pid}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"[UTT] main loop error: {e}")
            
        await asyncio.sleep(PROCESS_SLEEP_SEC)


async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    """Handle incoming audio frame"""
    if pid in EXCLUDE_PARTICIPANTS:
        return
    
    try:
        pcm, sr = _frame_to_float32_mono(frame)
        pcm16k = _resample_to_16k_mono(pcm, sr)
        
        if pid not in _first_frame_seen:
            logger.info(f"[AUDIO] first frame pid={pid} in_sr={sr} out_sr=16000 samples={len(pcm16k)}")
            _first_frame_seen.add(pid)
        
        _ensure_buffer(pid).append(pcm16k)
        
    except Exception as e:
        logger.error(f"[AUDIO] frame error pid={pid}: {e}", exc_info=False)


def setup_room_callbacks(room: rtc.Room):
    """Setup LiveKit room event handlers"""
    
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"[LK] participant_connected id={getattr(p, 'sid', 'n/a')} ident={p.identity}")
        if p.identity not in EXCLUDE_PARTICIPANTS:
            _ensure_utterance_state(p.identity)
            _ensure_buffer(p.identity)

    @room.on("track_published")
    def _track_pub(pub, participant):
        try:
            kind = getattr(pub, "kind", None) or getattr(pub, "track", {}).get("kind")
        except Exception:
            kind = "unknown"
        logger.info(f"[LK] track_published kind={kind} pub_sid={getattr(pub, 'sid', 'n/a')} participant={participant.identity}")

    @room.on("participant_disconnected")
    def _p_leave(p):
        pid = p.identity
        if pid in buffers:
            del buffers[pid]
        if pid in utterance_states:
            del utterance_states[pid]

    @room.on("track_subscribed")
    def _track_sub(track: rtc.Track, pub, participant):
        logger.info(f"[LK] track_subscribed kind={track.kind} track_sid={getattr(track, 'sid', 'n/a')} participant={participant.identity}")
        
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        
        pid = participant.identity or participant.sid
        if pid in EXCLUDE_PARTICIPANTS:
            logger.info(f"[LK] skipping excluded participant pid={pid}")
            return
        
        _ensure_utterance_state(pid)
        _ensure_buffer(pid)
        
        stream = rtc.AudioStream(track)
        first_frame = {"seen": False}
        
        async def consume():
            logger.info(f"[LK] consuming audio frames pid={pid} track_sid={getattr(track, 'sid', 'n/a')}")
            async for event in stream:
                if not first_frame["seen"]:
                    logger.info(f"[LK] first frame recv pid={pid} sr={event.frame.sample_rate} ch={event.frame.num_channels}")
                    first_frame["seen"] = True
                await _on_audio_frame(pid, event.frame)
        
        asyncio.create_task(consume())


async def join_livekit_room():
    """Connect to LiveKit room"""
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
    """Application lifespan manager"""
    logger.info("June STT Service starting")
    
    try:
        await whisper_service.initialize()
        logger.info("WhisperX ready (native VAD)")
    except Exception as e:
        logger.error(f"Service init failed: {e}")
        raise
        
    await join_livekit_room()
    
    task = None
    if room_connected:
        task = asyncio.create_task(_process_utterances())
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
    
    if room and room_connected:
        try:
            await room.disconnect()
        except Exception:
            pass


app = FastAPI(
    title="June STT",
    version="8.0.0-whisperx-native",
    description="Real-time Speech-to-Text with WhisperX native VAD",
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
    """OpenAI-compatible transcription endpoint"""
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
                "method": result.get("method", "whisperx_native"),
            }
        else:
            return {"text": text}
            
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/healthz")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "8.0.0-whisperx-native",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
            "vad": "whisperx_native",
        },
        "timing_config": {
            "max_utterance_sec": MAX_UTTERANCE_SEC,
            "min_utterance_sec": MIN_UTTERANCE_SEC,
            "silence_timeout_sec": SILENCE_TIMEOUT_SEC,
        }
    }


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "june-stt",
        "version": "8.0.0-whisperx-native",
        "description": "Real-time Speech-to-Text with WhisperX native VAD",
        "config": {
            "max_utterance_sec": MAX_UTTERANCE_SEC,
            "min_utterance_sec": MIN_UTTERANCE_SEC,
            "silence_timeout_sec": SILENCE_TIMEOUT_SEC,
        },
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
    """Detailed statistics endpoint"""
    return {
        "status": "success",
        "version": "8.0.0-whisperx-native",
        "connectivity": {
            "livekit_connected": room_connected,
            "orchestrator_available": orchestrator_available,
        },
        "features": {
            "vad": "whisperx_native",
            "streaming": STREAMING_ENABLED,
            "partials": PARTIALS_ENABLED,
        },
        "timing_config": {
            "max_utterance_sec": MAX_UTTERANCE_SEC,
            "min_utterance_sec": MIN_UTTERANCE_SEC,
            "silence_timeout_sec": SILENCE_TIMEOUT_SEC,
        },
        "global_stats": {
            "processed_utterances": processed_utterances,
            "partial_transcripts_sent": partial_transcripts_sent,
            "active_participants": len(buffers),
        },
        "metrics": streaming_metrics.get_stats(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
