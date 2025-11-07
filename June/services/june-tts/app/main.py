# app/main.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal, AsyncIterator

import os

import httpx
import ormsgpack
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field


@dataclass
class Settings:
    fish_base_url: str = os.getenv("FISH_SPEECH_BASE_URL", "http://fish-speech-server:8080")
    references_dir: Path = Path(os.getenv("REFERENCES_DIR", "/app/references"))
    timeout: float = float(os.getenv("FISH_SPEECH_TIMEOUT", "120"))


settings = Settings()


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)

    # Our external API
    voice_id: Optional[str] = Field(
        default=None,
        description="Maps to Fish-Speech reference_id (references/<voice_id>)",
    )

    format: Literal["wav", "pcm", "mp3"] = "wav"
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


app = FastAPI(
    title="Fish-Speech FastAPI Adapter",
    version="1.0.0",
    description="Thin FastAPI microservice on top of Fish-Speech /v1/tts (msgpack)",
)


async def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.fish_base_url, timeout=settings.timeout)


@app.get("/health")
async def health():
    """
    Health of adapter + upstream Fish-Speech /v1/health.
    """
    try:
        async with _new_client() as client:
            # upstream /v1/health is a simple JSON POST without body
            r = await client.post("/v1/health")
            upstream = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"upstream fish-speech unavailable: {exc}")

    return {"status": "ok", "upstream": upstream}


def _build_fish_payload(req: TTSRequest) -> dict:
    """
    Build the ServeTTSRequest-like payload expected by Fish-Speech.
    """
    return {
        "text": req.text,
        "chunk_length": req.chunk_length,
        "format": req.format,
        "mp3_bitrate": req.mp3_bitrate,
        "references": [],
        "reference_id": req.voice_id,
        "seed": req.seed,
        "use_memory_cache": "never",
        "normalize": req.normalize,
        "latency": req.latency,
        "streaming": req.streaming,
        "max_new_tokens": req.max_new_tokens,
        "top_p": req.top_p,
        "repetition_penalty": req.repetition_penalty,
        "temperature": req.temperature,
    }


@app.post("/tts")
async def tts(request: TTSRequest):
    """
    TTS endpoint for your stack.

    - Accepts JSON
    - Converts to Fish-Speech ServeTTSRequest
    - Sends as msgpack to /v1/tts
    """
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

        # non-streaming, full file
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
    """
    Register/update a cloned voice.

    Writes:
    - /app/references/<voice_id>/sample.ext
    - /app/references/<voice_id>/sample.lab

    Fish-Speech will use these when reference_id=<voice_id>.
    """
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
