#!/usr/bin/env python3
"""
June STT Service - LiveKit PCM → Whisper (PyAV-free)
Subscribes to room audio, converts rtc.AudioFrame to 16kHz float32 PCM,
streams to whisper for low-latency transcripts, and notifies orchestrator.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Deque, Tuple
from collections import deque

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import rtc
from scipy import signal

from config import config
from whisper_service import whisper_service
from livekit_token import connect_room_as_subscriber

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt")

room: Optional[rtc.Room] = None
room_connected: bool = False

ParticipantKey = str
buffers: dict[ParticipantKey, Deque[np.ndarray]] = {}
BUFFER_TARGET_SEC = 0.2  # lowered threshold for faster processing
SAMPLE_RATE = 16000

# Filter out TTS services from STT processing
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt"}


def _ensure_buffer(pid: ParticipantKey) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque()
    return buffers[pid]


def _analyze_audio(pcm: np.ndarray) -> dict:
    if pcm.size == 0:
        return {"rms": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
    # Guard against NaN/Inf
    pcm = np.nan_to_num(pcm, nan=0.0, posinf=0.0, neginf=0.0)
    rms = float(np.sqrt(np.mean(pcm ** 2)))
    return {"rms": rms, "min": float(pcm.min()), "max": float(pcm.max()), "mean": float(pcm.mean())}


def _gather_seconds(pid: ParticipantKey, seconds: float) -> Optional[np.ndarray]:
    buf = _ensure_buffer(pid)
    if not buf:
        return None
    target = int(seconds * SAMPLE_RATE)
    chunks = []
    total = 0
    while buf and total < target:
        x = buf.popleft()
        chunks.append(x)
        total += len(x)
    if not chunks:
        return None
    audio = np.concatenate(chunks, axis=0)
    if len(audio) > target:
        audio = audio[:target]
    return audio


async def _notify_orchestrator(user_id: str, text: str, language: Optional[str]):
    if not config.ORCHESTRATOR_URL:
        return
    payload = {
        "transcript_id": str(uuid.uuid4()),
        "user_id": user_id,
        "participant": user_id,          # required by orchestrator
        "event": "transcript",          # required by orchestrator
        "text": text,
        "language": language,
        "timestamp": datetime.utcnow().isoformat(),
        "room_name": "ozzu-main",
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{config.ORCHESTRATOR_URL}/api/webhooks/stt",
                json=payload,
            )
            if r.status_code != 200:
                logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
            else:
                logger.info(f"📤 Sent transcript to orchestrator: '{text}'")
    except Exception as e:
        logger.warning(f"Orchestrator notify error: {e}")


def _frame_to_float32_mono(frame: rtc.AudioFrame) -> Tuple[np.ndarray, int]:
    sr = frame.sample_rate
    ch = frame.num_channels
    buf = memoryview(frame.data)
    # Try int16 first, fallback to float32
    try:
        arr = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        arr = np.frombuffer(buf, dtype=np.float32)
    if ch and ch > 1:
        try:
            arr = arr.reshape(-1, ch).mean(axis=1)
        except Exception:
            # If reshape fails due to mismatch, best-effort mono
            frames = arr[: (len(arr) // ch) * ch]
            arr = frames.reshape(-1, ch).mean(axis=1)
    # Sanitize
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


async def _process_loop():
    logger.info("🔄 Starting audio processing loop")
    loop_count = 0
    while True:
        try:
            loop_count += 1
            active_participants = len(buffers)
            if loop_count % 25 == 0 and active_participants > 0:
                logger.info(f"🔊 Processing loop #{loop_count}: {active_participants} participants")
            
            for pid in list(buffers.keys()):
                # Skip TTS services - only process human participants
                if pid in EXCLUDE_PARTICIPANTS:
                    if loop_count % 50 == 0:  # Log occasionally
                        logger.info(f"⏭️ Skipping TTS participant: {pid}")
                    continue
                    
                buffer_size = len(buffers[pid])
                if buffer_size > 0 and loop_count % 10 == 0:
                    logger.info(f"📈 Buffer for {pid}: {buffer_size} chunks")
                
                audio = _gather_seconds(pid, BUFFER_TARGET_SEC)
                if audio is None or len(audio) < int(0.1 * SAMPLE_RATE):
                    continue
                stats = _analyze_audio(audio)
                logger.info(f"🔍 Audio stats [{pid}]: rms={stats['rms']:.6f} min={stats['min']:.3f} max={stats['max']:.3f} mean={stats['mean']:.6f} samples={len(audio)}")
                if not whisper_service.is_model_ready():
                    logger.warning("⚠️ Whisper model not ready")
                    continue
                logger.info(f"🎯 Processing {len(audio)} audio samples for {pid}")
                # Write chunk to a temp WAV and call whisper_service.transcribe on the path
                import tempfile, soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
                    res = await whisper_service.transcribe(tmp.name)
                text = res.get("text", "").strip()
                if text:
                    logger.info(f"✅ ASR[{pid}]: {text}")
                    await _notify_orchestrator(pid, text, res.get("language"))
                else:
                    logger.info(f"🔇 No speech detected for {pid}")
        except Exception as e:
            logger.warning(f"❌ Process loop error: {e}")
        await asyncio.sleep(0.2)


async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    if not hasattr(_on_audio_frame, 'frame_counts'):
        _on_audio_frame.frame_counts = {}
    if pid not in _on_audio_frame.frame_counts:
        _on_audio_frame.frame_counts[pid] = 0
    _on_audio_frame.frame_counts[pid] += 1
    if _on_audio_frame.frame_counts[pid] % 100 == 0:
        logger.info(f"📊 Received {_on_audio_frame.frame_counts[pid]} audio frames from {pid}")
    pcm, sr = _frame_to_float32_mono(frame)
    pcm16k = _resample_to_16k_mono(pcm, sr)
    _ensure_buffer(pid).append(pcm16k)


def join_livekit_room_sync_callbacks(room: rtc.Room):
    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"👤 Participant joined: {p.identity}")
    @room.on("participant_disconnected")
    def _p_leave(p):
        logger.info(f"👋 Participant left: {p.identity}")
    @room.on("track_published")
    def _track_pub(pub, participant):
        logger.info(f"📢 Track published by {participant.identity}: {pub.kind} - {pub.name}")
    @room.on("track_unpublished")
    def _track_unpub(pub, participant):
        logger.info(f"📢 Track unpublished by {participant.identity}: {pub.kind} - {pub.name}")
    @room.on("track_subscribed")
    def _track_sub(track: rtc.Track, pub, participant):
        logger.info(f"🎵 TRACK SUBSCRIBED: kind={track.kind}, participant={participant.identity}")
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            logger.info(f"❌ Skipping non-audio track: {track.kind}")
            return
        pid = participant.identity or participant.sid
        logger.info(f"✅ Subscribed to audio of {pid}")
        stream = rtc.AudioStream(track)
        async def consume():
            logger.info(f"🎧 Starting audio consumption for {pid}")
            async for event in stream:
                await _on_audio_frame(pid, event.frame)
        asyncio.create_task(consume())
    @room.on("track_unsubscribed")
    def _track_unsub(track, pub, participant):
        logger.info(f"🔇 Unsubscribed from track of {participant.identity}")


async def join_livekit_room():
    global room, room_connected
    logger.info("Connecting STT to LiveKit via orchestrator token")
    room = rtc.Room()
    join_livekit_room_sync_callbacks(room)
    await connect_room_as_subscriber(room, "june-stt")
    room_connected = True
    logger.info("STT connected and listening for audio frames")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 June STT (LiveKit PCM pipeline)")
    try:
        await whisper_service.initialize()
        logger.info("✅ Whisper ready")
    except Exception as e:
        logger.error(f"Whisper init failed: {e}")
    await join_livekit_room()
    task = asyncio.create_task(_process_loop())
    yield
    task.cancel()
    if room and room_connected:
        await room.disconnect()


app = FastAPI(title="June STT", version="6.2.7-webhook-payload", description="LiveKit PCM → Whisper (orchestrator tokens)", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],)

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "whisper_ready": whisper_service.is_model_ready(),
        "livekit_connected": room_connected,
    }

@app.get("/")
async def root():
    return {"service": "june-stt", "version": "6.2.7-webhook-payload", "pcm_pipeline": True, "sample_rate": SAMPLE_RATE}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)