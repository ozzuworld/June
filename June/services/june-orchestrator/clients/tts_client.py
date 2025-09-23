import os
from typing import Optional
import httpx
from fastapi import HTTPException


async def tts_generate(client: httpx.AsyncClient, base_url: Optional[str], payload: dict) -> bytes:
    base = base_url or os.getenv("TTS_BASE_URL")
    if not base:
        raise HTTPException(status_code=500, detail="TTS_BASE_URL not configured")
    url = f"{base.rstrip('/')}/tts/generate"

    try:
        resp = await client.post(url, json=payload)
    except (httpx.ConnectError, httpx.ReadTimeout) as e:
        raise HTTPException(status_code=502, detail=f"TTS upstream unavailable: {e}") from e

    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="TTS upstream error")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.content
