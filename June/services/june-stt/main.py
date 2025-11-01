#!/usr/bin/env python3
"""
June STT Enhanced - Combining faster-whisper-server with LiveKit Integration
OpenAI API compatible + Real-time voice chat capabilities
"""
import asyncio
import logging
import uuid
import tempfile
import soundfile as sf
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Deque, Dict, Any
from collections import deque

import numpy as np
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from livekit import rtc
from scipy import signal
import httpx

from config import config
from whisper_service import whisper_service
from livekit_token import connect_room_as_subscriber

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt-enhanced")

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, dict] = {}
processed_utterances = 0
skipped_chunks = 0

# Constants from your original implementation
SAMPLE_RATE = 16000
START_THRESHOLD_RMS = 0.012
CONTINUE_THRESHOLD_RMS = 0.006
END_SILENCE_SEC = 0.8
MAX_UTTERANCE_SEC = 6.0
MIN_UTTERANCE_SEC = 0.8
PROCESS_SLEEP_SEC = 0.1
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_voice_at: Optional[datetime] = None
        self.total_samples = 0

# Helper functions (from your original implementation)
def _ensure_utterance_state(pid: str) -> UtteranceState:
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
    return utterance_states[pid]

def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=300)
    return buffers[pid]

def _calculate_rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0.0

def _should_start_utterance(rms: float, state: UtteranceState) -> bool:
    return not state.is_active and rms > START_THRESHOLD_RMS

def _should_continue_utterance(rms: float, state: UtteranceState) -> bool:
    if not state.is_active:
        return False
    now = datetime.utcnow()
    if rms > CONTINUE_THRESHOLD_RMS:
        state.last_voice_at = now
        return True
    if state.last_voice_at:
        silence_duration = (now - state.last_voice_at).total_seconds()
        return silence_duration < END_SILENCE_SEC
    return True

def _should_end_utterance(state: UtteranceState) -> bool:
    if not state.is_active:
        return False
    now = datetime.utcnow()
    if state.started_at and (now - state.started_at).total_seconds() > MAX_UTTERANCE_SEC:
        return True
    if state.last_voice_at:
        silence_duration = (now - state.last_voice_at).total_seconds()
        if silence_duration >= END_SILENCE_SEC:
            if state.started_at:
                total_duration = (now - state.started_at).total_seconds()
                return total_duration >= MIN_UTTERANCE_SEC
    return False

def _get_utterance_audio(state: UtteranceState) -> Optional[np.ndarray]:
    if not state.buffer:
        return None
    audio = np.concatenate(list(state.buffer), axis=0)
    duration_sec = len(audio) / SAMPLE_RATE
    if duration_sec < MIN_UTTERANCE_SEC:
        logger.debug(f"🔇 Utterance too short: {duration_sec:.2f}s < {MIN_UTTERANCE_SEC}s")
        return None
    return audio

def _reset_utterance_state(state: UtteranceState):
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_voice_at = None
    state.total_samples = 0

async def _notify_orchestrator(user_id: str, text: str, language: Optional[str]):
    if not config.ORCHESTRATOR_URL:
        return

    payload = {
        "transcript_id": str(uuid.uuid4()),
        "user_id": user_id,
        "participant": user_id,
        "event": "transcript",
        "text": text,
        "language": language,
        "timestamp": datetime.utcnow().isoformat(),
        "room_name": "ozzu-main",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{config.ORCHESTRATOR_URL}/api/webhooks/stt",
                json=payload,
            )
            if r.status_code == 429:
                logger.info(f"🛡️ Rate limited by orchestrator (expected protection): {r.text}")
            elif r.status_code != 200:
                logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
            else:
                logger.info(f"📤 Sent transcript to orchestrator: '{text}'")
    except Exception as e:
        logger.warning(f"Orchestrator notify error: {e}")

# LiveKit audio processing (from your original implementation)
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

async def _transcribe_utterance(pid: str, audio: np.ndarray):
    """Transcribe a complete utterance"""
    global processed_utterances
    
    if not whisper_service.is_model_ready():
        logger.warning("⚠️ Whisper model not ready")
        return

    try:
        duration = len(audio) / SAMPLE_RATE
        rms = _calculate_rms(audio)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        
        logger.info(f"🎯 Transcribing utterance for {pid}: {duration:.2f}s, rms={rms:.4f}, peak={peak:.3f}")
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None)

        text = res.get("text", "").strip()
        method = res.get("method", "unknown")
        processing_time = res.get("processing_time_ms", 0)

        if text and len(text) > 2:
            if text.lower() not in ["you", "you.", "uh", "um", "ah", "mm", "hm", "er"]:
                logger.info(f"✅ UTTERANCE[{pid}] via {method} ({processing_time}ms, {duration:.2f}s): {text}")
                await _notify_orchestrator(pid, text, res.get("language"))
                processed_utterances += 1
            else:
                logger.debug(f"🚫 Filtered utterance from {pid}: '{text}' (common false positive)")
        else:
            reason = res.get("skipped_reason", "empty_or_short")
            logger.debug(f"🔇 No valid text for {pid}: {reason}")

    except Exception as e:
        logger.error(f"❌ Transcription error for {pid}: {e}")

async def _process_utterances():
    """Process complete utterances using VAD-based endpointing"""
    global processed_utterances, skipped_chunks
    
    logger.info(f"🚀 Starting UTTERANCE-LEVEL STT processing")
    logger.info(f"🎯 Endpointing: start_rms≥{START_THRESHOLD_RMS}, continue_rms≥{CONTINUE_THRESHOLD_RMS}, end_silence≤{END_SILENCE_SEC}s")

    while True:
        try:
            for pid in list(buffers.keys()):
                if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
                    continue

                state = _ensure_utterance_state(pid)
                buf = _ensure_buffer(pid)
                
                while buf:
                    frame = buf.popleft()
                    rms = _calculate_rms(frame)
                    
                    if _should_start_utterance(rms, state):
                        logger.info(f"🎬 Starting utterance for {pid} (rms={rms:.4f})")
                        state.is_active = True
                        state.started_at = datetime.utcnow()
                        state.last_voice_at = datetime.utcnow()
                        state.buffer.clear()
                        state.buffer.append(frame)
                        state.total_samples = len(frame)
                        
                    elif _should_continue_utterance(rms, state):
                        state.buffer.append(frame)
                        state.total_samples += len(frame)
                        if rms > CONTINUE_THRESHOLD_RMS:
                            state.last_voice_at = datetime.utcnow()
                        
                    elif _should_end_utterance(state):
                        utterance_audio = _get_utterance_audio(state)
                        if utterance_audio is not None:
                            duration = len(utterance_audio) / SAMPLE_RATE
                            logger.info(f"🎬 Ending utterance for {pid}: {duration:.2f}s, {len(utterance_audio)} samples")
                            await _transcribe_utterance(pid, utterance_audio)
                        else:
                            logger.debug(f"🔇 Discarded short utterance for {pid}")
                            skipped_chunks += 1
                        _reset_utterance_state(state)
                    
                    # Force end very long utterances
                    if state.is_active and state.started_at:
                        duration = (datetime.utcnow() - state.started_at).total_seconds()
                        if duration > MAX_UTTERANCE_SEC:
                            logger.info(f"⏰ Force-ending long utterance for {pid}: {duration:.2f}s")
                            utterance_audio = _get_utterance_audio(state)
                            if utterance_audio is not None:
                                await _transcribe_utterance(pid, utterance_audio)
                            _reset_utterance_state(state)

        except Exception as e:
            logger.warning(f"❌ Utterance processing error: {e}")

        await asyncio.sleep(PROCESS_SLEEP_SEC)

async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
        return
    
    pcm, sr = _frame_to_float32_mono(frame)
    pcm16k = _resample_to_16k_mono(pcm, sr)
    _ensure_buffer(pid).append(pcm16k)

# LiveKit room setup (from your original implementation)
def setup_room_callbacks(room: rtc.Room):
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"👤 Participant joined: {p.identity}")
        if p.identity in EXCLUDE_PARTICIPANTS:
            logger.info(f"🚫 Participant {p.identity} is EXCLUDED from STT processing")

    @room.on("participant_disconnected")
    def _p_leave(p):
        logger.info(f"👋 Participant left: {p.identity}")
        if p.identity in buffers:
            del buffers[p.identity]
        if p.identity in utterance_states:
            del utterance_states[p.identity]

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
    logger.info(f"🚀 June STT Enhanced - faster-whisper + LiveKit Integration")
    logger.info(f"Features: OpenAI API Compatible + Real-time Voice Chat")

    try:
        await whisper_service.initialize()
        logger.info("✅ Whisper service ready")
    except Exception as e:
        logger.error(f"Whisper init failed: {e}")

    await join_livekit_room()
    
    if room_connected:
        task = asyncio.create_task(_process_utterances())
    
    yield
    
    if room_connected and 'task' in locals():
        task.cancel()
    if room and room_connected:
        await room.disconnect()

# FastAPI application
app = FastAPI(
    title="June STT Enhanced",
    version="4.0.0-enhanced",
    description="OpenAI-compatible transcription + LiveKit real-time voice chat",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI-compatible endpoints (like faster-whisper-server)
@app.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
    temperature: Optional[float] = Form(0.0),
    timestamp_granularities: Optional[str] = Form(None),
    stream: Optional[bool] = Form(False)
):
    """OpenAI-compatible transcription endpoint"""
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Whisper model not ready")
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            
            # Transcribe using our whisper service
            result = await whisper_service.transcribe(tmp.name, language=language)
            
        # Format response to match OpenAI API
        text = result.get("text", "")
        
        if response_format == "text":
            return text
        elif response_format == "verbose_json":
            return {
                "task": "transcribe",
                "language": result.get("language", language or "en"),
                "duration": result.get("duration", 0),
                "text": text,
                "segments": result.get("segments", [])
            }
        else:  # json
            return {"text": text}
            
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Health check endpoint
@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "version": "4.0.0-enhanced",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "livekit_connected": room_connected,
            "batched_inference": config.USE_BATCHED_INFERENCE,
            "vad_enabled": config.VAD_ENABLED
        },
        "features": {
            "openai_api_compatible": True,
            "real_time_voice_chat": config.LIVEKIT_ENABLED,
            "utterance_level_processing": True,
            "anti_feedback": True,
            "speech_endpointing": True
        },
        "utterance_processing": {
            "start_threshold_rms": START_THRESHOLD_RMS,
            "continue_threshold_rms": CONTINUE_THRESHOLD_RMS,
            "end_silence_sec": END_SILENCE_SEC,
            "min_utterance_sec": MIN_UTTERANCE_SEC,
            "max_utterance_sec": MAX_UTTERANCE_SEC,
            "excluded_participants": list(EXCLUDE_PARTICIPANTS)
        }
    }

@app.get("/")
async def root():
    return {
        "service": "june-stt-enhanced",
        "version": "4.0.0-enhanced", 
        "description": "OpenAI-compatible transcription + LiveKit real-time voice chat",
        "endpoints": {
            "transcriptions": "/v1/audio/transcriptions",
            "health": "/healthz",
            "stats": "/stats"
        },
        "features": [
            "OpenAI API compatibility",
            "Real-time LiveKit integration", 
            "Utterance-level processing",
            "Multi-participant voice chat",
            "Orchestrator integration",
            "Dynamic model loading"
        ],
        "stats": {
            "processed_utterances": processed_utterances,
            "skipped_chunks": skipped_chunks,
            "success_rate": f"{processed_utterances/(processed_utterances+skipped_chunks or 1):.1%}"
        }
    }

@app.get("/stats")
async def stats():
    """Detailed statistics"""
    active_participants = list(buffers.keys())
    utterance_participants = list(utterance_states.keys())
    
    participant_stats = {}
    for pid in utterance_participants:
        state = utterance_states[pid]
        participant_stats[pid] = {
            "is_active": state.is_active,
            "buffer_frames": len(state.buffer),
            "total_samples": state.total_samples,
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "duration_sec": (datetime.utcnow() - state.started_at).total_seconds() if state.started_at else 0
        }
    
    return {
        "status": "success",
        "global_stats": {
            "processed_utterances": processed_utterances,
            "skipped_chunks": skipped_chunks,
            "success_rate": f"{processed_utterances/(processed_utterances+skipped_chunks or 1):.1%}",
            "active_participants": len(active_participants),
            "utterance_participants": len(utterance_participants)
        },
        "participants": participant_stats
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
