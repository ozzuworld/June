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


@dataclass
class Settings:
    fish_base_url: str = os.getenv("FISH_SPEECH_BASE_URL", "http://127.0.0.1:8080")
    references_dir: Path = Path(os.getenv("REFERENCES_DIR", "/app/references"))
    timeout: float = float(os.getenv("FISH_SPEECH_TIMEOUT", "120"))


settings = Settings()


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice_id: Optional[str] = Field(
        default=None,
        description="Maps to Fish-Speech reference_id (references/<voice_id>)",
    )
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
    """Request model for orchestrator-compatible /api/tts/synthesize endpoint"""
    text: str = Field(..., min_length=1)
    room_name: str = Field(..., description="LiveKit room name to publish audio to")
    language: str = Field(default="en", description="Language code (en, zh, jp, ko, yue)")
    stream: bool = Field(default=True, description="Enable streaming synthesis")


app = FastAPI(
    title="June TTS (Fish-Speech)",
    version="1.1.0",
    description="FastAPI wrapper around Fish-Speech /v1/tts with orchestrator compatibility.",
)


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.fish_base_url, timeout=settings.timeout)


@app.get("/health")
async def health():
    try:
        async with _new_client() as client:
            r = await client.post("/v1/health")
            upstream = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"upstream fish-speech unavailable: {exc}")

    return {"status": "ok", "upstream": upstream}


def _build_fish_payload(req: TTSRequest) -> dict:
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


@app.post("/api/tts/synthesize")
async def api_synthesize_speech(request: SynthesizeRequest):
    """
    Synthesize speech using Fish-Speech TTS (orchestrator-compatible endpoint)
    
    This endpoint is called by june-orchestrator to generate and publish TTS audio.
    It wraps the Fish-Speech TTS service and returns a JSON response.
    
    Args:
        request: SynthesizeRequest with text, room_name, language, and stream options
        
    Returns:
        JSON response with synthesis status and metrics
        
    Note:
        Currently returns audio via Fish-Speech but does not yet publish to LiveKit room.
        LiveKit publishing logic should be implemented here or in a separate service.
    """
    start_time = time.time()
    
    try:
        # Convert orchestrator request to Fish-Speech TTS request
        tts_request = TTSRequest(
            text=request.text,
            voice_id=None,  # Use default voice; could be mapped from language
            streaming=request.stream,
            format="wav",
            chunk_length=200,
            normalize=True,
            latency="balanced"
        )
        
        # Build Fish-Speech payload
        fish_payload = _build_fish_payload(tts_request)
        body = ormsgpack.packb(fish_payload)
        
        # Call Fish-Speech TTS service
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
            
            # Get audio data
            audio_data = resp.content
            audio_size = len(audio_data)
            
            # Calculate metrics
            synthesis_time_ms = (time.time() - start_time) * 1000
            
            # Estimate chunks (assuming ~1KB per chunk for streaming)
            chunks_sent = max(1, audio_size // 1024)
            
            # TODO: Implement LiveKit room publishing here
            # For now, we just generate the audio and return success
            # In production, you should:
            # 1. Connect to LiveKit room using room_name
            # 2. Publish audio_data to the room
            # 3. Track actual chunks sent
            
            return JSONResponse({
                "status": "success",
                "chunks_sent": chunks_sent,
                "synthesis_time_ms": round(synthesis_time_ms, 2),
                "room_name": request.room_name,
                "text_length": len(request.text),
                "audio_size_bytes": audio_size,
                "language": request.language,
                "note": "Audio generated successfully. LiveKit publishing not yet implemented."
            })
            
    except httpx.TimeoutException:
        synthesis_time_ms = (time.time() - start_time) * 1000
        raise HTTPException(
            status_code=504,
            detail=f"TTS synthesis timeout after {synthesis_time_ms:.0f}ms"
        )
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Fish-Speech service: {str(e)}"
        )
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
