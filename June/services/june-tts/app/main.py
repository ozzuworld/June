from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal, AsyncIterator
import time
import os
import httpx
import ormsgpack
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import numpy as np
from io import BytesIO
import asyncio
import soundfile as sf
from livekit import rtc

@dataclass
class Settings:
    fish_base_url: str = os.getenv("FISH_SPEECH_BASE_URL", "http://127.0.0.1:8080")
    references_dir: Path = Path(os.getenv("REFERENCES_DIR", "/app/references"))
    timeout: float = float(os.getenv("FISH_SPEECH_TIMEOUT", "120"))

settings = Settings()

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice_id: Optional[str] = Field(default=None)
    format: Literal["wav", "flac", "mp3"] = "wav"
    mp3_bitrate: Literal[64, 128, 192] = 128
    chunk_length: int = 200
    normalize: bool = True
    latency: Literal["normal", "balanced"] = "normal"
    streaming: bool = False
    max_new_tokens: int = 1024
    top_p: float = 0.7
    repetition_penalty: float = 1.2
    temperature: float = 0.7
    seed: Optional[int] = None

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(...)
    language: str = Field(default="en")
    stream: bool = Field(default=True)

app = FastAPI(
    title="June TTS (Fish-Speech)",
    version="1.3.0",
    description="FastAPI wrapper around Fish-Speech /v1/tts with persistent LiveKit publisher integration.",
)

# Global publisher state
livekit_room = None
livekit_audio_track = None
livekit_connected = False
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")

# Utilities

def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.fish_base_url, timeout=settings.timeout)

def _build_fish_payload(req: TTSRequest) -> dict:
    return {
        "text": req.text,
        "chunk_length": req.chunk_length,
        "format": req.format,
        "mp3_bitrate": req.mp3_bitrate,
        "references": [],
        "reference_id": req.voice_id,
        "seed": req.seed,
        "use_memory_cache": "off",
        "normalize": req.normalize,
        "latency": req.latency,
        "streaming": req.streaming,
        "max_new_tokens": req.max_new_tokens,
        "top_p": req.top_p,
        "repetition_penalty": req.repetition_penalty,
        "temperature": req.temperature,
    }

async def get_livekit_token(identity: str, room_name: str) -> tuple[str, str]:
    orchestrator_url = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")
    url = f"{orchestrator_url}/token"
    payload = {"roomName": room_name, "participantName": identity}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        ws_url = data.get("livekitUrl") or data.get("ws_url")
        token = data["token"]
        if not ws_url:
            raise RuntimeError(f"Orchestrator response missing livekitUrl/ws_url: {data}")
        return ws_url, token

async def connect_livekit_publisher():
    global livekit_room, livekit_audio_track, livekit_connected
    try:
        ws_url, token = await get_livekit_token(LIVEKIT_IDENTITY, LIVEKIT_ROOM_NAME)
        room = rtc.Room()
        await room.connect(ws_url, token)
        audio_track = rtc.LocalAudioTrack("TTS Audio", 16000, 1)
        await room.publish_track(audio_track)
        livekit_room = room
        livekit_audio_track = audio_track
        livekit_connected = True
        print(f"[LiveKit] Connected as {LIVEKIT_IDENTITY} in {LIVEKIT_ROOM_NAME}")
    except Exception as e:
        print(f"[LiveKit] Failed to connect: {e}")

async def publish_audio_to_livekit(pcm_audio: np.ndarray, sample_rate: int = 16000):
    global livekit_audio_track, livekit_connected
    if not livekit_connected or livekit_audio_track is None:
        print("[LiveKit] Not connected. Cannot publish!")
        return
    frame_size = int(sample_rate * 0.02)
    for offset in range(0, len(pcm_audio), frame_size):
        frame_data = pcm_audio[offset:offset+frame_size]
        if len(frame_data) < frame_size:
            frame_data = np.pad(frame_data, (0, frame_size-len(frame_data)), 'constant')
        pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
        livekit_audio_track.send_frame(pcm_int16.tobytes())
        await asyncio.sleep(0.02)
    print(f"[LiveKit] Audio published.")

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(connect_livekit_publisher())

@app.get("/health")
async def health():
    try:
        async with _new_client() as client:
            r = await client.post("/v1/health")
            upstream = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"upstream fish-speech unavailable: {exc}")
    return {"status": "ok", "upstream": upstream}

@app.post("/api/tts/synthesize")
async def api_synthesize_speech(request: SynthesizeRequest):
    start_time = time.time()
    try:
        tts_request = TTSRequest(
            text=request.text,
            voice_id=None,
            streaming=request.stream,
            format="wav",
            chunk_length=200,
            normalize=True,
            latency="balanced"
        )
        fish_payload = _build_fish_payload(tts_request)
        body = ormsgpack.packb(fish_payload)
        async with _new_client() as client:
            headers = {"content-type": "application/msgpack"}
            resp = await client.post(
                "/v1/tts",
                content=body,
                headers=headers,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Fish-Speech TTS failed: {resp.text}"
                )
            audio_data = resp.content
            audio_size = len(audio_data)
            synthesis_time_ms = (time.time() - start_time) * 1000
            # Decode WAV to PCM
            with BytesIO(audio_data) as bio:
                wav_data, sr = sf.read(bio, dtype='float32')
                if len(wav_data.shape) > 1:
                    wav_data = wav_data[:, 0]
                if sr != 16000:
                    from scipy.signal import resample_poly
                    wav_data = resample_poly(wav_data, 16000, sr)
                    sr = 16000
            # Publish to LiveKit
            await publish_audio_to_livekit(wav_data, sr)
            chunks_sent = max(1, audio_size // 1024)
            return JSONResponse({
                "status": "success",
                "chunks_sent": chunks_sent,
                "synthesis_time_ms": round(synthesis_time_ms, 2),
                "room_name": request.room_name,
                "text_length": len(request.text),
                "audio_size_bytes": audio_size,
                "language": request.language,
                "note": "Audio generated and published to LiveKit."
            })
    except Exception as e:
        synthesis_time_ms = (time.time() - start_time) * 1000
        raise HTTPException(
            status_code=500,
            detail=f"TTS synthesis failed after {synthesis_time_ms:.0f}ms: {str(e)}"
        )

@app.post("/tts")
async def tts(request: TTSRequest):
    fish_payload = _build_fish_payload(request)
    body = ormsgpack.packb(fish_payload)
    async with _new_client() as client:
        headers = {"content-type": "application/msgpack"}
        if request.streaming:
            upstream = await client.stream(
                "POST",
                "/v1/tts",
                content=body,
                headers=headers,
            )
            if upstream.status_code != 200:
                body_bytes = await upstream.aread()
                raise HTTPException(
                    status_code=upstream.status_code,
                    detail=body_bytes.decode("utf-8", errors="ignore"),
                )
            content_type = upstream.headers.get("content-type", "audio/wav")
            content_disp = upstream.headers.get(
                "content-disposition", f'attachment; filename="audio.{request.format}"'
            )
            async def iter_bytes() -> AsyncIterator[bytes]:
                async for chunk in upstream.aiter_bytes():
                    if chunk:
                        yield chunk
            return StreamingResponse(
                iter_bytes(),
                media_type=content_type,
                headers={"Content-Disposition": content_disp},
            )
        resp = await client.post(
            "/v1/tts",
            content=body,
            headers=headers,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        content_type = resp.headers.get("content-type", "audio/wav")
        content_disp = resp.headers.get(
            "content-disposition", f'attachment; filename="audio.{request.format}"'
        )
        async def single_chunk() -> AsyncIterator[bytes]:
            yield resp.content
        return StreamingResponse(
            single_chunk(),
            media_type=content_type,
            headers={"Content-Disposition": content_disp},
        )
@app.post("/voices/{voice_id}")
async def create_or_update_voice(
    voice_id: str,
    reference_audio: UploadFile = File(...),
    reference_text: str = Form(...),
):
    base_dir: Path = settings.references_dir
    voice_dir = base_dir / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)
    original_name = reference_audio.filename or "sample.wav"
    suffix = Path(original_name).suffix or ".wav"
    audio_path = voice_dir / f"sample{suffix}"
    lab_path = audio_path.with_suffix(".lab")
    audio_bytes = await reference_audio.read()
    audio_path.write_bytes(audio_bytes)
    lab_path.write_text(reference_text.strip(), encoding="utf-8")
    return JSONResponse(
        {
            "voice_id": voice_id,
            "audio_path": str(audio_path),
            "lab_path": str(lab_path),
            "message": "voice registered; use this voice_id in /tts",
        }
    )