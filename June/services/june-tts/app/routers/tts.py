from typing import AsyncIterator, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict, HttpUrl

from app.core.openvoice_engine import synthesize_v2_to_wav_path

router = APIRouter(prefix="/tts", tags=["tts"])


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    reference_b64: Optional[str] = None       # WAV/MP3/FLAC/OGG/etc (base64-encoded bytes)
    reference_url: Optional[HttpUrl] = None   # will be downloaded server-side
    voice_id: str = "base"                    # kept for API consistency; Melo pack selects actual voice
    language: str = "en"                      # en, es, fr, zh, ja, ko
    format: str = "wav"                       # output container (fixed to wav for now)
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 0.0
    metadata: dict = Field(default_factory=dict)


async def _file_stream(path: str) -> AsyncIterator[bytes]:
    chunk = 64 * 1024
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            yield data


@router.post("/generate")
async def generate(req: TTSRequest):
    # Guard clauses
    if not req.text or len(req.text.strip()) == 0:
        raise HTTPException(status_code=400, detail="text is required")
    if req.format.lower() != "wav":
        raise HTTPException(status_code=415, detail="Only wav output is supported")
    if not (req.reference_b64 or req.reference_url):
        raise HTTPException(status_code=400, detail="Provide reference_b64 or reference_url for cloning")

    wav_path = await synthesize_v2_to_wav_path(
        text=req.text.strip(),
        language=req.language.strip().lower(),
        reference_b64=req.reference_b64,
        reference_url=str(req.reference_url) if req.reference_url else None,
        speed=req.speed,
        volume=req.volume,
        pitch=req.pitch,
        metadata=req.metadata,
    )

    return StreamingResponse(_file_stream(wav_path), media_type="audio/wav")
