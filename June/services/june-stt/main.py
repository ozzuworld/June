#!/usr/bin/env python3
"""
June STT Service - LiveKit PCM → faster-whisper v1.2.0
Real-time transcription with simplified chunking and faster-whisper built-ins
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
# Option A: fixed-size chunking, let faster-whisper handle silence
CHUNK_SEC = 1.0         # 1.0s chunks
MIN_CHUNK_SEC = 0.5     # skip if we have less than 0.5s
SAMPLE_RATE = 16000

# Filter out TTS services from STT processing
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt"}


def _ensure_buffer(pid: ParticipantKey) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque(maxlen=100)  # prevent unbounded growth
    return buffers[pid]


def _gather_seconds(pid: ParticipantKey, seconds: float) -> Optional[np.ndarray]:
    """Gather approximately `seconds` of audio from the participant buffer."""
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
        "participant": user_id,
        "event": "transcript",
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


async def _process_loop():
    """Main audio processing loop using fixed-size chunking (Option A)."""
    logger.info(f"🚀 Starting STT loop - batched: {config.USE_BATCHED_INFERENCE}, VAD: {config.VAD_ENABLED}")
    loop_count = 0

    while True:
        try:
            loop_count += 1

            for pid in list(buffers.keys()):
                # Skip TTS services
                if pid in EXCLUDE_PARTICIPANTS:
                    continue

                # Get a fixed-size chunk
                audio = _gather_seconds(pid, CHUNK_SEC)
                if audio is None or len(audio) < int(MIN_CHUNK_SEC * SAMPLE_RATE):
                    continue

                if not whisper_service.is_model_ready():
                    logger.warning("⚠️ Whisper model not ready")
                    continue

                logger.info(f"🎯 Processing {len(audio)} samples for {pid} via "
                            f"{'batched' if config.USE_BATCHED_INFERENCE else 'regular'} pipeline")

                import tempfile, soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    sf.write(tmp.name, audio, SAMPLE_RATE, subtype='PCM_16')
                    res = await whisper_service.transcribe(tmp.name, language=config.LANGUAGE)

                text = res.get("text", "").strip()
                method = res.get("method", "unknown")
                processing_time = res.get("processing_time_ms", 0)

                if text:
                    logger.info(f"✅ ASR[{pid}] via {method} ({processing_time}ms): {text}")
                    await _notify_orchestrator(pid, text, res.get("language"))
                else:
                    reason = res.get("skipped_reason", "empty")
                    logger.debug(f"🔇 No text for {pid}: {reason}")

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
        if p.identity in buffers:
            del buffers[p.identity]

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
    logger.info(f"🚀 June STT v2.0 - faster-whisper {'' if config.USE_BATCHED_INFERENCE else 'non-'}batched mode")
    logger.info(f"Features: VAD={config.VAD_ENABLED}, Batch size={config.BATCH_SIZE if config.USE_BATCHED_INFERENCE else 'N/A'}")

    try:
        await whisper_service.initialize()
        logger.info("✅ Whisper service ready")
    except Exception as e:
        logger.error(f"Whisper init failed: {e}")

    await join_livekit_room()
    task = asyncio.create_task(_process_loop())

    yield

    task.cancel()
    if room and room_connected:
        await room.disconnect()


app = FastAPI(
    title="June STT v2.0",
    version="2.0.0-faster-whisper-v1.2.0",
    description="Simplified STT with faster-whisper built-ins",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "whisper_ready": whisper_service.is_model_ready(),
        "livekit_connected": room_connected,
        "batched_inference": config.USE_BATCHED_INFERENCE,
        "vad_enabled": config.VAD_ENABLED,
        "version": "2.0.0-faster-whisper-v1.2.0",
    }

@app.get("/")
async def root():
    return {
        "service": "june-stt",
        "version": "2.0.0-faster-whisper-v1.2.0",
        "features": {
            "batched_inference": config.USE_BATCHED_INFERENCE,
            "vad_enabled": config.VAD_ENABLED,
            "silence_detection": "built-in (faster-whisper)",
            "custom_filters": "minimal",
        },
        "sample_rate": SAMPLE_RATE,
        "chunk_sec": CHUNK_SEC,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
