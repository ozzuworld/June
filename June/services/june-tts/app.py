# app/main.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal, AsyncIterator

import os

import httpx
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
    # Mapped to Fish-Speech "reference_id" (folder under /app/references)
    voice_id: Optional[str] = Field(
        default=None,
        description="Voice ID / reference_id used by Fish-Speech (maps to references/<voice_id>)",
    )
    format: Literal["wav", "flac", "mp3"] = "wav"
    chunk_length: int = 200
    normalize: bool = True
    streaming: bool = False
    max_new_tokens: int = 1024
    top_p: float = 0.7
    repetition_penalty: float = 1.2
    temperature: float = 0.7
    seed: Optional[int] = None


app = FastAPI(
    title="Fish-Speech FastAPI Adapter",
    version="1.0.0",
    description="Thin FastAPI microservice on top of OpenAudio / Fish-Speech /v1/tts",
)


async def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.fish_base_url, timeout=settings.timeout)


@app.get("/health")
async def health():
    """
    Basic health + upstream Fish-Speech health.
    """
    try:
        async with _new_client() as client:
            r = await client.post("/v1/health")
            upstream = r.json()
    except Exception as exc:
        # upstream is down or unreachable
        raise HTTPException(status_code=503, detail=f"upstream fish-speech unavailable: {exc}")

    return {"status": "ok", "upstream": upstream}


@app.post("/tts")
async def tts(request: TTSRequest):
    """
    TTS endpoint.

    - If voice_id is provided, it is passed as reference_id to Fish-Speech,
      which expects references/<voice_id>/*.{wav,flac,mp3}+*.lab.
    """
    # Build Fish-Speech ServeTTSRequest-compatible payload
    payload = {
        "text": request.text,
        "chunk_length": request.chunk_length,
        "format": request.format,
        # we let Fish-Speech look up references by reference_id in /app/references
        "references": [],  # explicit empty list, matches the docs
        "reference_id": request.voice_id,
        "seed": request.seed,
        "use_memory_cache": "off",
        "normalize": request.normalize,
        "streaming": request.streaming,
        "max_new_tokens": request.max_new_tokens,
        "top_p": request.top_p,
        "repetition_penalty": request.repetition_penalty,
        "temperature": request.temperature,
    }

    async with _new_client() as client:
        if request.streaming:
            # Streamed proxy
            upstream = await client.stream("POST", "/v1/tts", json=payload)

            if upstream.status_code != 200:
                body = await upstream.aread()
                raise HTTPException(
                    status_code=upstream.status_code,
                    detail=body.decode("utf-8", errors="ignore"),
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

        # Non-streaming: we wait for the full file
        resp = await client.post("/v1/tts", json=payload)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        content_type = resp.headers.get("content-type", "audio/wav")
        content_disp = resp.headers.get(
            "content-disposition", f'attachment; filename="audio.{request.format}"'
        )

        # Single-chunk StreamingResponse to avoid loading twice
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

    Writes into REFERENCES_DIR / <voice_id>:
      - sample.<ext> (uploaded audio)
      - sample.lab   (reference text)

    Fish-Speech will automatically pick these up when reference_id=voice_id.
    """
    # Where we write references (must be a volume shared with fish-speech server)
    base_dir: Path = settings.references_dir
    voice_dir = base_dir / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    # Determine extension; default to .wav
    original_name = reference_audio.filename or "sample.wav"
    suffix = Path(original_name).suffix or ".wav"

    audio_path = voice_dir / f"sample{suffix}"
    lab_path = audio_path.with_suffix(".lab")

    # Save audio file
    audio_bytes = await reference_audio.read()
    audio_path.write_bytes(audio_bytes)

    # Save label (reference text)
    lab_path.write_text(reference_text.strip(), encoding="utf-8")

    return JSONResponse(
        {
            "voice_id": voice_id,
            "audio_path": str(audio_path),
            "lab_path": str(lab_path),
            "message": "voice registered; use this voice_id as reference_id in /tts",
        }
    )
