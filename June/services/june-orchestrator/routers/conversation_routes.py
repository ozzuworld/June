from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.conversation import ConversationInput, ConversationOutput, MessageArtifact
from dependencies.auth import get_current_user
from clients.http import get_http_client
from clients.tts_client import tts_generate

router = APIRouter(prefix="/v1", tags=["conversation"])


@router.post("/conversation", response_model=ConversationOutput)
async def process_conversation(
    payload: ConversationInput,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http = Depends(get_http_client),
) -> ConversationOutput:
    # Guard clauses
    if not (payload.text or payload.audio_b64):
        raise HTTPException(status_code=400, detail="Provide text or audio_b64.")

    # Example: choose a path based on inputs (text -> TTS echo; audio -> TODO: STT first)
    is_text = bool(payload.text)
    if not is_text and payload.audio_b64:
        # In a fuller flow: run STT first, then orchestrate; here we signal unsupported for brevity
        raise HTTPException(status_code=422, detail="audio_b64 path not yet implemented in this patch")

    # Happy path: echo text -> TTS bytes via external TTS (async, RORO)
    # Required env: TTS_BASE_URL
    tts_payload = {
        "text": payload.text,
        "voice_id": payload.voice_id or "default",
        "format": "wav",
        "language": payload.language or "en",
        "metadata": payload.metadata or {},
    }

    audio_bytes = await tts_generate(http, base_url=None, payload=tts_payload)  # base_url resolved in client
    if not audio_bytes or len(audio_bytes) < 8:
        raise HTTPException(status_code=502, detail="TTS failed to generate audio")

    # In a real system you'd persist message rows here with db (AsyncSession).
    message = MessageArtifact(
        id="msg_temp_1",
        role="assistant",
        text=payload.text,
        audio_url=None,  # if you persist and serve from object storage, return a URL
    )

    return ConversationOutput(
        ok=True,
        conversation_id="conv_temp_1",
        message=message,
        used_tools=["tts"],
        warnings=[],
        errors=[],
    )
