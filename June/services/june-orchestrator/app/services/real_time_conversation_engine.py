# Real-Time Conversation Engine - SOTA Natural Flow Implementation
# Fix: convert Session.Message objects to simple dicts for context/history usage

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime
import json

from ..core.dependencies import get_redis_client, get_session_service

logger = logging.getLogger(__name__)

@dataclass
class ConversationState:
    session_id: str
    is_ai_speaking: bool = False
    is_user_speaking: bool = False
    last_user_input_time: Optional[datetime] = None
    last_ai_response_time: Optional[datetime] = None
    current_ai_task: Optional[asyncio.Task] = None
    pending_interruption: bool = False
    conversation_complexity: str = "simple"
    turn_count: int = 0

class RealTimeConversationEngine:
    def __init__(self, redis_client=None, tts_service=None, streaming_ai_service=None):
        self.redis = redis_client or get_redis_client()
        self.tts = tts_service
        self.streaming_ai = streaming_ai_service
        self.active_conversations: Dict[str, ConversationState] = {}
        self.SIMPLE_RESPONSE_MAX_MS = 200
        self.NORMAL_RESPONSE_MAX_MS = 800
        self.PHRASE_MIN_TOKENS = 4
        self.TOKEN_GAP_THRESHOLD_MS = 80
        self.INTERRUPTION_DETECT_MS = 200
        self.TURN_TAKING_PAUSE_MS = 150

    def _msg_to_dict(self, m) -> Dict[str, Any]:
        # Session.Message domain model → simple dict accepted by build_context_for_voice
        try:
            return {"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")}
        except Exception:
            # Already a dict or unknown object
            return m if isinstance(m, dict) else {"role": "user", "content": str(m)}

    async def _get_history(self, room_name: str, user_id: str) -> List[Dict[str, Any]]:
        session_service = get_session_service()
        session = await session_service.get_or_create_for_room(room_name, user_id)
        return [self._msg_to_dict(m) for m in list(session.messages)]

    async def _preprocess_ai_response(self, session_id: str, room_name: str, user_id: str, text: str):
        try:
            from ..services.ai_service import build_context_for_voice
            history = await self._get_history(room_name, user_id)
            context = build_context_for_voice(text, history, user_id)
            await self.redis.setex(f"preprocess:{session_id}", 30, json.dumps({"context": context, "text": text, "ts": time.time()}))
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")

    async def handle_user_input(self, session_id: str, room_name: str, text: str, audio_data: Optional[bytes] = None, is_partial: bool = False) -> Dict[str, Any]:
        start = time.time()
        state = self.active_conversations.get(session_id) or ConversationState(session_id=session_id)
        self.active_conversations[session_id] = state
        if is_partial:
            if len(text.split()) >= 3 and text.endswith(('.', '?', '!')):
                if not state.current_ai_task or state.current_ai_task.done():
                    state.current_ai_task = asyncio.create_task(self._preprocess_ai_response(session_id, room_name, session_id, text))
            return {"processed": "partial"}
        history = await self._get_history(room_name, session_id)
        phrase_count = 0
        async def tts_cb(phrase: str):
            nonlocal phrase_count
            phrase_count += 1
            try:
                await self.tts.publish_to_room(room_name=room_name, text=phrase, language="en")
            except Exception as e:
                logger.warning(f"TTS publish error: {e}")
        try:
            from ..services.ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, history, session_id)
            first_phrase_time = None
            tokens = []
            async for token in self.streaming_ai.generate_streaming_response(text=text, conversation_history=history, user_id=session_id, session_id=session_id, tts_callback=tts_cb):
                tokens.append(token)
                if first_phrase_time is None and phrase_count > 0:
                    first_phrase_time = (time.time() - start) * 1000
            total = (time.time() - start) * 1000
            return {
                "response": "".join(tokens),
                "phrases_sent": phrase_count,
                "total_time_ms": total,
                "first_phrase_time_ms": first_phrase_time or total,
                "complexity": "medium",
                "target_met": (first_phrase_time or total) <= 800
            }
        except Exception as e:
            logger.error(f"RT engine failed: {e}")
            await tts_cb("I'm sorry, I had a technical issue. Can you try again?")
            return {"error": str(e)}

    async def handle_voice_onset(self, session_id: str, room_name: str) -> Dict[str, Any]:
        return {"handled": True, "session_id": session_id, "time": datetime.utcnow().isoformat()}

    def get_conversation_stats(self, session_id: str) -> Dict[str, Any]:
        st = self.active_conversations.get(session_id)
        return {"active": bool(st), "session_id": session_id}

    def get_global_stats(self) -> Dict[str, Any]:
        return {"active_conversations": len(self.active_conversations), "engine_type": "real_time_sota"}
