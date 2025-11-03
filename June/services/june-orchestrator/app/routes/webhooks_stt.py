"""STT webhook route additions for interruption signaling"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from ..core.dependencies import (
    session_service_dependency,
    emotion_service_dependency,
)
from ..services.emotion_intelligence_service import InterruptionHandler
from ..core.dependencies import get_redis_client

logger = logging.getLogger(__name__)
router = APIRouter()

class SttEvent(BaseModel):
    session_id: str
    transcript: Optional[str] = None
    audio_data: Optional[str] = None
    event: str  # 'partial' | 'final' | 'voice_onset'
    room_name: Optional[str] = None

# Lazy singleton for interruption handler
_interrupt_handler: Optional[InterruptionHandler] = None

def get_interrupt_handler() -> InterruptionHandler:
    global _interrupt_handler
    if _interrupt_handler is None:
        _interrupt_handler = InterruptionHandler(get_redis_client())
    return _interrupt_handler

@router.post("/stt/event")
async def stt_event(
    ev: SttEvent,
    sessions = Depends(session_service_dependency),
    emotion = Depends(emotion_service_dependency),
):
    try:
        room = ev.room_name or (sessions.get_room_for_session(ev.session_id) if hasattr(sessions, 'get_room_for_session') else ev.session_id)
        if ev.event == 'voice_onset':
            res = await get_interrupt_handler().handle_interruption(ev.session_id, room)
            return {"ok": True, "interruption": res}
        return {"ok": True}
    except Exception as e:
        logger.error(f"STT event error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
