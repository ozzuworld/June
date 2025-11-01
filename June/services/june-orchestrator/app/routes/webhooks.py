# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture with skill-based AI + STREAMING
STT → Orchestrator (WITH MEMORY + SKILLS + SECURITY + STREAMING) → TTS (voice cloning for skills)

STREAMING ENHANCEMENTS:
- Partial transcript support from STT
- Concurrent AI + TTS processing
- Sentence-level TTS triggering
- First-token and first-audio latency tracking

SECURITY ENHANCEMENTS:
- Duplicate message detection
- Rate limiting per user  
- AI cost tracking
- Circuit breaker protection

CHATTERBOX TTS INTEGRATION:
- Voice registry for speaker resolution
- Emotion and pacing controls
- Enhanced voice cloning support
"""
import os
import logging
import httpx
import uuid
import asyncio
import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from ..config import config
from ..services.ai_service import generate_response
from ..services.streaming_service import streaming_ai_service
from ..session_manager import session_manager
from ..services.skill_service import skill_service
from ..services.voice_profile_service import voice_profile_service
from ..security.rate_limiter import rate_limiter, duplication_detector
from ..security.cost_tracker import call_tracker, circuit_breaker
from ..voice_registry import resolve_voice_reference, validate_voice_reference

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------- Robust feature flags (config attribute -> env fallback -> default) ----------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED       = getattr(config, "ORCH_STREAMING_ENABLED", _bool_env("ORCH_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED  = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
PARTIAL_SUPPORT_ENABLED = getattr(config, "PARTIAL_SUPPORT_ENABLED", _bool_env("PARTIAL_SUPPORT_ENABLED", True))

# ---------- Models ----------

class STTWebhookPayload(BaseModel):
    event: str
    room_name: str
    participant: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    segments: Optional[List[Dict[str, Any]]] = []
    audio_data: Optional[bytes] = None
    transcript_id: Optional[str] = None
    partial: bool = Field(False, description="Whether this is a partial transcript")

class TTSPublishRequest(BaseModel):
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    speaker_wav: Optional[str] = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0)
    streaming: bool = Field(False, description="Enable streaming TTS")

# ---------- Helpers ----------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

async def _trigger_streaming_tts(room_name: str, text: str, language: str = "en",
                                 use_voice_cloning: bool = False, user_id: Optional[str] = None,
                                 speaker: Optional[str] = None, speaker_wav: Optional[str] = None,
                                 exaggeration: float = 0.6, cfg_weight: float = 0.8) -> Dict[str, Any]:
    try:
        tts_url = f"{config.services.tts_base_url}/stream-to-room"
        # Resolve voice
        if use_voice_cloning and user_id:
            refs = voice_profile_service.get_user_references(user_id)
            resolved = refs[0] if refs else resolve_voice_reference(speaker, speaker_wav)
        else:
            resolved = resolve_voice_reference(speaker, speaker_wav)
        if not validate_voice_reference(resolved):
            return {"success": False, "error": "Invalid voice reference"}
        payload = {
            "text": text,
            "language": language,
            "speaker_wav": [resolved] if resolved else None,
            "exaggeration": _clamp(exaggeration, 0.0, 2.0),
            "cfg_weight": _clamp(cfg_weight, 0.1, 1.0)
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(tts_url, json=payload)
        if r.status_code == 200:
            res = r.json()
            logger.info(f"✅ Streaming TTS: first_audio={res.get('first_audio_ms',0)}ms total={res.get('total_time_ms',0)}ms")
            return {"success": True, **res}
        return {"success": False, "error": f"TTS HTTP {r.status_code}"}
    except Exception as e:
        logger.error(f"❌ Streaming TTS error: {e}")
        return {"success": False, "error": str(e)}

async def _trigger_tts(room_name: str, text: str, language: str = "en",
                       use_voice_cloning: bool = False, user_id: Optional[str] = None,
                       speaker: Optional[str] = None, speaker_wav: Optional[str] = None,
                       exaggeration: float = 0.6, cfg_weight: float = 0.8,
                       streaming: bool = False):
    if streaming and STREAMING_ENABLED:
        return await _trigger_streaming_tts(room_name, text, language, use_voice_cloning, user_id,
                                            speaker, speaker_wav, exaggeration, cfg_weight)
    # Non-streaming path
    try:
        tts_url = f"{config.services.tts_base_url}/publish-to-room"
        if use_voice_cloning and user_id:
            refs = voice_profile_service.get_user_references(user_id)
            resolved = refs[0] if refs else resolve_voice_reference(speaker, speaker_wav)
        else:
            resolved = resolve_voice_reference(speaker, speaker_wav)
        if not validate_voice_reference(resolved):
            raise HTTPException(status_code=400, detail="Invalid voice reference")
        payload = {
            "text": text,
            "language": language,
            "speaker_wav": [resolved] if resolved else None,
            "speed": 1.0,
            "exaggeration": _clamp(exaggeration, 0.0, 2.0),
            "cfg_weight": _clamp(cfg_weight, 0.1, 1.0),
            "streaming": False
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(tts_url, json=payload)
        if r.status_code != 200:
            logger.error(f"❌ TTS failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"❌ TTS error: {e}")

# ---------- Routes ----------

@router.post("/api/webhooks/stt")
async def handle_stt_webhook(payload: STTWebhookPayload, authorization: str = Header(None)):
    # Partial transcripts path
    if payload.partial and PARTIAL_SUPPORT_ENABLED:
        logger.info(f"⚡ PARTIAL transcript from {payload.participant}: {payload.text}")
        return {"status": "partial_acknowledged", "participant": payload.participant}

    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")

    # Security checks
    if not rate_limiter.check_request_rate_limit(payload.participant):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    can_call, reason = circuit_breaker.should_allow_call()
    if not can_call:
        raise HTTPException(status_code=503, detail=f"Service temporarily unavailable: {reason}")

    try:
        session = session_manager.get_or_create_session_for_room(
            room_name=payload.room_name, user_id=payload.participant
        )
        message_id = payload.transcript_id or str(uuid.uuid4())
        if duplication_detector.is_duplicate_message(session.session_id, message_id, payload.text,
                                                     payload.participant, payload.timestamp):
            return {"status": "duplicate_blocked", "message_id": message_id}
        duplication_detector.mark_message_processed(session.session_id, message_id, payload.text,
                                                   payload.participant, payload.timestamp)

        skill_trigger = skill_service.detect_skill_trigger(payload.text)
        if skill_trigger:
            name, sdef = skill_trigger
            return await _handle_skill_activation(session, name, sdef, payload)
        elif session.skill_session.is_active():
            return await _handle_skill_input(session, payload)
        else:
            return await _handle_conversation(session, payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Webhook processing error")
        raise HTTPException(status_code=500, detail=str(e))

async def _handle_conversation(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    # AI rate limiting
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")

    history = session.get_recent_history()
    if STREAMING_ENABLED:
        return await _handle_streaming_conversation(session, payload, history)
    else:
        ai_text, proc_ms = await generate_response(
            text=payload.text, user_id=payload.participant, session_id=session.session_id,
            conversation_history=history
        )
        call_tracker.track_call(input_text=f"{payload.text} {str(history)}", output_text=ai_text,
                                processing_time_ms=proc_ms)
        session_manager.add_to_history(session.session_id, "user", payload.text,
                                       metadata={"confidence": payload.confidence, "language": payload.language,
                                                 "timestamp": payload.timestamp})
        session_manager.add_to_history(session.session_id, "assistant", ai_text,
                                       metadata={"processing_time_ms": proc_ms, "model": config.ai.model})
        session_manager.update_session_metrics(session.session_id,
                                               tokens_used=len(payload.text)//4 + len(ai_text)//4,
                                               response_time_ms=proc_ms)
        await _trigger_tts(payload.room_name, ai_text, payload.language or "en",
                           speaker=getattr(config.ai, 'default_speaker', None), streaming=False)
        return {"status": "success", "session_id": session.session_id, "ai_response": ai_text,
                "processing_time_ms": proc_ms}

async def _handle_streaming_conversation(session, payload: STTWebhookPayload, history: List[Dict]) -> Dict[str, Any]:
    start = time.time()
    async def tts_cb(sentence: str):
        await _trigger_tts(payload.room_name, sentence, payload.language or "en",
                           speaker=getattr(config.ai, 'default_speaker', None), streaming=True)
    parts = []
    first_token_ms = None
    async for token in streaming_ai_service.generate_streaming_response(
        text=payload.text, conversation_history=history, user_id=payload.participant,
        session_id=session.session_id, tts_callback=tts_cb if CONCURRENT_TTS_ENABLED else None
    ):
        if first_token_ms is None:
            first_token_ms = (time.time() - start) * 1000
            logger.info(f"⚡ First AI token in {first_token_ms:.0f}ms")
        parts.append(token)
    ai_text = "".join(parts)
    total_ms = (time.time() - start) * 1000
    call_tracker.track_call(input_text=f"{payload.text} {str(history)}", output_text=ai_text,
                            processing_time_ms=total_ms)
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"confidence": payload.confidence, "language": payload.language,
                                             "timestamp": payload.timestamp})
    session_manager.add_to_history(session.session_id, "assistant", ai_text,
                                   metadata={"processing_time_ms": total_ms, "model": config.ai.model,
                                             "streaming": True})
    session_manager.update_session_metrics(session.session_id,
                                           tokens_used=len(payload.text)//4 + len(ai_text)//4,
                                           response_time_ms=total_ms)
    if not CONCURRENT_TTS_ENABLED and ai_text:
        await _trigger_tts(payload.room_name, ai_text, payload.language or "en",
                           speaker=getattr(config.ai, 'default_speaker', None), streaming=True)
    return {"status": "streaming_success", "session_id": session.session_id, "ai_response": ai_text,
            "processing_time_ms": round(total_ms, 2), "first_token_ms": round(first_token_ms or 0, 2),
            "concurrent_tts_used": CONCURRENT_TTS_ENABLED, "streaming_mode": True}

# ---------- Skills (existing behavior preserved) ----------

async def _handle_skill_activation(session, skill_name: str, skill_def, payload: STTWebhookPayload) -> Dict[str, Any]:
    session.skill_session.activate_skill(skill_name)
    ai_response = skill_def.activation_response
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"skill_trigger": skill_name, "confidence": payload.confidence,
                                             "language": payload.language, "timestamp": payload.timestamp})
    session_manager.add_to_history(session.session_id, "assistant", ai_response,
                                   metadata={"skill_activation": skill_name, "processing_time_ms": 50})
    await _trigger_tts(payload.room_name, ai_response, payload.language or "en",
                       speaker=getattr(config.ai, 'default_speaker', None), streaming=False)
    return {"status": "skill_activated", "skill_name": skill_name, "session_id": session.session_id,
            "ai_response": ai_response, "processing_time_ms": 50,
            "skill_state": session.skill_session.to_dict()}

async def _handle_skill_input(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    name = session.skill_session.active_skill
    if skill_service.should_exit_skill(payload.text, session.skill_session):
        session.skill_session.deactivate_skill()
        ai_response = "Skill deactivated. I'm back to normal conversation mode."
        await _trigger_tts(payload.room_name, ai_response, payload.language or "en",
                           speaker=getattr(config.ai, 'default_speaker', None), streaming=False)
        return {"status": "skill_deactivated", "ai_response": ai_response, "session_id": session.session_id}
    ai_response, ctx = skill_service.create_skill_response(name, payload.text, session.skill_session.context)
    session.skill_session.context.update(ctx)
    session.skill_session.increment_turn()
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"skill_input": name, "skill_turn": session.skill_session.turn_count,
                                             "confidence": payload.confidence, "language": payload.language})
    session_manager.add_to_history(session.session_id, "assistant", ai_response,
                                   metadata={"skill_response": name, "skill_turn": session.skill_session.turn_count,
                                             "processing_time_ms": 100})
    use_cloning = ctx.get("use_voice_cloning", False)
    await _trigger_tts(payload.room_name, ai_response, payload.language or "en",
                       use_voice_cloning=use_cloning,
                       user_id=payload.participant if use_cloning else None,
                       speaker=getattr(config.ai, 'default_speaker', None) if not use_cloning else None,
                       streaming=False)
    return {"status": "skill_processed", "skill_name": name, "session_id": session.session_id,
            "ai_response": ai_response, "processing_time_ms": 100,
            "skill_state": session.skill_session.to_dict(), "voice_cloning_used": use_cloning}
