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
BUFFER_TARGET_SEC = 1.0
SAMPLE_RATE = 16000


def _ensure_buffer(pid: ParticipantKey) -> Deque[np.ndarray]:
    if pid not in buffers:
        buffers[pid] = deque()
    return buffers[pid]


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
        "text": text,
        "language": language,
        "timestamp": datetime.utcnow().isoformat(),
        "room_name": "ozzu-main",
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{config.ORCHESTRATOR_URL}/api/webhooks/transcript",
                json=payload,
            )
            if r.status_code != 200:
                logger.warning(f"Orchestrator webhook failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.warning(f"Orchestrator notify error: {e}")


def _frame_to_float32_mono(frame: rtc.AudioFrame) -> Tuple[np.ndarray, int]:
    sr = frame.sample_rate
    ch = frame.num_channels
    arr = np.frombuffer(frame.data, dtype=np.float32)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1).astype(np.float32)
    return arr, sr


def _resample_to_16k_mono(pcm: np.ndarray, sr: int) -> np.ndarray:
    if sr == SAMPLE_RATE:
        return pcm
    gcd = np.gcd(sr, SAMPLE_RATE)
    up = SAMPLE_RATE // gcd
    down = sr // gcd
    return signal.resample_poly(pcm, up, down).astype(np.float32)


async def _process_loop():
    while True:
        try:
            for pid in list(buffers.keys()):
                audio = _gather_seconds(pid, BUFFER_TARGET_SEC)
                if audio is None or len(audio) < int(0.5 * SAMPLE_RATE):
                    continue
                if not whisper_service.is_model_ready():
                    continue
                res = await whisper_service.transcribe_array(audio, SAMPLE_RATE)
                text = res.get("text", "").strip()
                if text:
                    logger.info(f"ASR[{pid}]: {text}")
                    await _notify_orchestrator(pid, text, res.get("language"))
        except Exception as e:
            logger.warning(f"process loop error: {e}")
        await asyncio.sleep(0.2)


async def _on_audio_frame(pid: str, frame: rtc.AudioFrame):
    pcm, sr = _frame_to_float32_mono(frame)
    pcm16k = _resample_to_16k_mono(pcm, sr)
    _ensure_buffer(pid).append(pcm16k)


async def join_livekit_room():
    global room, room_connected
    logger.info("Connecting STT to LiveKit via orchestrator token")

    room = rtc.Room()

    @room.on("participant_connected")
    def _p_join(p):
        logger.info(f"Participant joined: {p.identity}")

    @room.on("track_subscribed")
    async def _track_sub(track: rtc.Track, pub, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        pid = participant.identity or participant.sid
        logger.info(f"Subscribed to audio of {pid}")
        stream = rtc.AudioStream(track)
        async def consume():
            async for f in stream:
                await _on_audio_frame(pid, f)
        asyncio.create_task(consume())

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


app = FastAPI(title="June STT", version="6.1.0", description="LiveKit PCM → Whisper (orchestrator tokens)", lifespan=lifespan)
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
    return {"service": "june-stt", "version": "6.1.0", "pcm_pipeline": True, "sample_rate": SAMPLE_RATE}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
