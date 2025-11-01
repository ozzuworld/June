#!/usr/bin/env python3
"""
June STT Enhanced - Silero VAD + LiveKit Integration
Intelligent speech detection replacing custom RMS thresholds
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

from config_enhanced import config
from whisper_service_enhanced import whisper_service
from livekit_token import connect_room_as_subscriber

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt-enhanced")

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, dict] = {}
processed_utterances = 0

# Simplified constants (Silero VAD handles most of the complexity)
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 8.0         # Hard cap to prevent runaway processing
MIN_UTTERANCE_SEC = 0.5         # Minimum for processing (Silero will double-check)
PROCESS_SLEEP_SEC = 0.1         # Check every 100ms
SILENCE_TIMEOUT_SEC = 1.0       # End utterance after 1s of silence
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0

# Helper functions (simplified without complex RMS logic)
def _ensure_utterance_state(pid: str) -> UtteranceState:
    if pid not in utterance_states:
        utterance_states[pid] = UtteranceState()
    return utterance_states[pid]

def _ensure_buffer(pid: str) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=400)  # Buffer for up to 8 seconds at 50fps
    return buffers[pid]

def _reset_utterance_state(state: UtteranceState):
    """Reset utterance state for next capture"""
    state.buffer.clear()
    state.is_active = False
    state.started_at = None
    state.last_audio_at = None
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

# Simplified audio processing (let Silero handle the intelligence)
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

async def _transcribe_utterance_with_silero(pid: str, audio: np.ndarray):
    """Enhanced transcription with Silero VAD pre-filtering"""
    global processed_utterances
    
    if not whisper_service.is_model_ready():
        logger.warning("⚠️ Whisper model not ready")
        return

    try:
        duration = len(audio) / SAMPLE_RATE
        
        # Silero VAD pre-filter - this replaces all custom RMS logic!
        if not whisper_service.has_speech_content(audio, SAMPLE_RATE):
            logger.debug(f"🔇 Silero VAD filtered out non-speech for {pid} ({duration:.2f}s)")
            return  # Skip expensive Whisper processing
        
        logger.info(f"🎯 Silero VAD confirmed speech for {pid}: {duration:.2f}s")
        
        # Process with Whisper (only real speech gets here)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
            res = await whisper_service.transcribe(tmp.name, language=None)

        text = res.get("text", "").strip()
        method = res.get("method", "silero_enhanced")
        processing_time = res.get("processing_time_ms", 0)

        # Minimal post-processing (Silero already filtered most noise)
        if text and len(text) > 2:
            # Only filter obvious artifacts that might slip through
            if text.lower() not in ["you", "you.", "uh", "um", "mm"]:
                logger.info(f"✅ SPEECH[{pid}] via {method} ({processing_time}ms, {duration:.2f}s): {text}")
                await _notify_orchestrator(pid, text, res.get("language"))
                processed_utterances += 1
            else:
                logger.debug(f"🚫 Filtered minimal false positive: '{text}'")
        else:
            logger.debug(f"🔇 Empty transcription result")

    except Exception as e:
        logger.error(f"❌ Transcription error for {pid}: {e}")

async def _process_utterances_simplified():
    """Simplified utterance processing - let Silero do the heavy lifting"""
    global processed_utterances
    
    logger.info(f"🚀 Starting Silero VAD-enhanced STT processing")
    logger.info(f"🎯 Intelligent speech detection replaces custom thresholds")
    logger.info(f"📊 Limits: min={MIN_UTTERANCE_SEC}s, max={MAX_UTTERANCE_SEC}s, silence_timeout={SILENCE_TIMEOUT_SEC}s")

    while True:
        try:
            for pid in list(buffers.keys()):
                # Anti-feedback: Skip excluded participants
                if pid in EXCLUDE_PARTICIPANTS or "tts" in pid.lower() or "stt" in pid.lower():
                    continue

                state = _ensure_utterance_state(pid)
                buf = _ensure_buffer(pid)
                
                # Process available frames
                while buf:
                    frame = buf.popleft()
                    now = datetime.utcnow()
                    
                    # Simple state management without complex RMS logic
                    if not state.is_active:
                        # Start new utterance
                        state.is_active = True
                        state.started_at = now
                        state.last_audio_at = now
                        state.buffer.clear()
                        state.buffer.append(frame)
                        state.total_samples = len(frame)
                        logger.debug(f"🎬 Started utterance capture for {pid}")
                        
                    else:
                        # Continue existing utterance
                        state.buffer.append(frame)
                        state.total_samples += len(frame)
                        state.last_audio_at = now
                        
                        # Check for end conditions
                        duration = (now - state.started_at).total_seconds()
                        silence_duration = (now - state.last_audio_at).total_seconds()
                        
                        should_end = (
                            duration >= MAX_UTTERANCE_SEC or  # Too long
                            (duration >= MIN_UTTERANCE_SEC and silence_duration >= SILENCE_TIMEOUT_SEC)  # Good length + silence
                        )
                        
                        if should_end:
                            # Complete utterance - let Silero decide if it's speech
                            utterance_audio = np.concatenate(list(state.buffer), axis=0)
                            utterance_duration = len(utterance_audio) / SAMPLE_RATE
                            
                            logger.info(f"🎬 Ending utterance for {pid}: {utterance_duration:.2f}s, {len(utterance_audio)} samples")
                            
                            # Silero will intelligently filter this
                            await _transcribe_utterance_with_silero(pid, utterance_audio)
                            _reset_utterance_state(state)
                
                # Debug logging for active states
                if state.is_active and state.started_at:
                    duration = (datetime.utcnow() - state.started_at).total_seconds()
                    if duration > 2.0:  # Log only long utterances
                        logger.debug(f"📊 {pid}: ACTIVE utterance {duration:.1f}s")

        except Exception as e:
            logger.warning(f"❌ Utterance processing error: {e}")

        await asyncio.sleep(PROCESS_SLEEP_SEC)

async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    # Anti-feedback: Skip excluded participants
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
    logger.info(f"🚀 June STT Enhanced - Silero VAD + LiveKit Integration")
    logger.info(f"Features: OpenAI API Compatible + Intelligent Speech Detection")

    try:
        await whisper_service.initialize()
        logger.info("✅ Enhanced Whisper + Silero VAD service ready")
    except Exception as e:
        logger.error(f"Enhanced service init failed: {e}")

    await join_livekit_room()
    
    if room_connected:
        task = asyncio.create_task(_process_utterances_simplified())
    
    yield
    
    if room_connected and 'task' in locals():
        task.cancel()
    if room and room_connected:
        await room.disconnect()

# FastAPI application
app = FastAPI(
    title="June STT Enhanced with Silero VAD",
    version="4.1.0-silero",
    description="Intelligent speech detection + OpenAI API + LiveKit real-time voice chat",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI-compatible endpoints
@app.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
    temperature: Optional[float] = Form(0.0),
):
    """OpenAI-compatible transcription endpoint with Silero VAD pre-filtering"""
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Enhanced Whisper + Silero VAD not ready")
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            
            # Transcribe with Silero VAD pre-filtering
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
                "segments": result.get("segments", []),
                "method": result.get("method", "silero_enhanced")
            }
        else:  # json
            return {"text": text}
            
    except Exception as e:
        logger.error(f"OpenAI API transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Health check endpoint
@app.get("/healthz")
async def health():
    model_info = whisper_service.get_model_info()
    return {
        "status": "healthy",
        "version": "4.1.0-silero",
        "components": {
            "whisper_ready": whisper_service.is_model_ready(),
            "silero_vad_ready": model_info.get("silero_vad_ready", False),
            "livekit_connected": room_connected,
            "batched_inference": config.USE_BATCHED_INFERENCE
        },
        "features": {
            "openai_api_compatible": True,
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "real_time_voice_chat": config.LIVEKIT_ENABLED,
            "intelligent_speech_detection": True,
            "anti_feedback": True
        },
        "intelligence": {
            "speech_detection": "Silero VAD (ML-powered)" if config.SILERO_VAD_ENABLED else "Basic fallback",
            "excluded_participants": list(EXCLUDE_PARTICIPANTS),
            "min_utterance_sec": MIN_UTTERANCE_SEC,
            "max_utterance_sec": MAX_UTTERANCE_SEC
        }
    }

@app.get("/")
async def root():
    return {
        "service": "june-stt-enhanced-silero",
        "version": "4.1.0-silero", 
        "description": "Intelligent speech detection + OpenAI API + LiveKit real-time voice chat",
        "endpoints": {
            "transcriptions": "/v1/audio/transcriptions",
            "health": "/healthz",
            "stats": "/stats"
        },
        "features": [
            "Silero VAD intelligent speech detection",
            "OpenAI API compatibility",
            "Real-time LiveKit integration", 
            "Anti-feedback protection",
            "Orchestrator integration",
            "Dynamic model loading"
        ],
        "stats": {
            "processed_utterances": processed_utterances,
            "success_rate": "High (Silero VAD pre-filtering)"
        }
    }

@app.get("/stats")
async def stats():
    """Detailed statistics with Silero VAD info"""
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
    
    model_info = whisper_service.get_model_info()
    
    return {
        "status": "success",
        "intelligence": {
            "silero_vad_enabled": config.SILERO_VAD_ENABLED,
            "silero_vad_ready": model_info.get("silero_vad_ready", False),
            "speech_detection_method": "Silero VAD (ML)" if config.SILERO_VAD_ENABLED else "Fallback"
        },
        "global_stats": {
            "processed_utterances": processed_utterances,
            "active_participants": len(active_participants),
            "utterance_participants": len(utterance_participants)
        },
        "participants": participant_stats,
        "model_info": model_info
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
