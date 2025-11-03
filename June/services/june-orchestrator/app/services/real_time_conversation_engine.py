# Real-Time Conversation Engine - SOTA Natural Flow Implementation
# Based on 2024-2025 voice AI research: sub-1.5s latency, phrase streaming, full-duplex

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Callable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime
import json

from ..core.dependencies import get_redis_client

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
    """SOTA conversation engine achieving <1.5s latency with natural turn-taking"""
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
        self.hesitation_patterns = {
            "processing": ["Hmm,", "Let me think,", "Well,"],
            "complex": ["That's a great question.", "Interesting point."],
            "simple": []
        }

    async def start_conversation_session(self, session_id: str, room_name: str) -> ConversationState:
        state = ConversationState(session_id=session_id)
        self.active_conversations[session_id] = state
        logger.info(f"🎙️ Started real-time conversation session: {session_id}")
        return state

    async def handle_user_input(self, session_id: str, room_name: str, text: str, audio_data: Optional[bytes] = None, is_partial: bool = False) -> Dict[str, Any]:
        start_time = time.time()
        state = self.active_conversations.get(session_id) or await self.start_conversation_session(session_id, room_name)
        if state.is_ai_speaking and not is_partial:
            await self._handle_interruption(session_id, room_name, text)
            state.pending_interruption = False
        if is_partial:
            return await self._handle_partial_input(session_id, text, state)
        state.last_user_input_time = datetime.utcnow()
        state.is_user_speaking = False
        state.turn_count += 1
        complexity = self._analyze_input_complexity(text, state)
        target_latency = self._get_target_latency(complexity)
        return await self._generate_timed_response(session_id, room_name, text, complexity, target_latency, start_time)

    async def _handle_interruption(self, session_id: str, room_name: str, user_text: str):
        state = self.active_conversations[session_id]
        if not self._is_valid_interruption(user_text):
            return
        if state.current_ai_task and not state.current_ai_task.done():
            state.current_ai_task.cancel()
        try:
            await self._stop_tts_in_room(room_name)
        except Exception as e:
            logger.warning(f"TTS stop failed: {e}")
        await self.tts.publish_to_room(room_name=room_name, text="Yes?", language="en")
        state.is_ai_speaking = False
        state.pending_interruption = False

    def _is_valid_interruption(self, text: str) -> bool:
        t = text.lower().strip()
        if t in ['um', 'uh', 'hmm', 'ah', 'er', 'well']:
            return False
        if len(t) < 3:
            return False
        for signal in ['wait', 'stop', 'hold on', 'actually', 'no', 'but', 'however', 'what', 'how', 'why', 'can you', 'i need', 'sorry', 'excuse me']:
            if signal in t:
                return True
        return False

    async def _handle_partial_input(self, session_id: str, partial_text: str, state: ConversationState) -> Dict[str, Any]:
        if len(partial_text.split()) >= 3 and partial_text.endswith(('.', '?', '!')):
            if not state.current_ai_task or state.current_ai_task.done():
                state.current_ai_task = asyncio.create_task(self._preprocess_ai_response(session_id, partial_text))
        return {"processed": "partial", "early_start": bool(state.current_ai_task)}

    async def _preprocess_ai_response(self, session_id: str, text: str):
        try:
            from ..services.ai_service import build_context_for_voice
            from ..core.dependencies import get_conversation_processor
            processor = get_conversation_processor()
            history = processor.session_service.get_history(session_id)
            context = build_context_for_voice(text, history, "user")
            await self.redis.setex(f"preprocess:{session_id}", 30, json.dumps({"context": context, "text": text, "timestamp": time.time()}))
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")

    def _analyze_input_complexity(self, text: str, state: ConversationState) -> str:
        wc = len(text.split())
        if wc <= 3: return "simple"
        if any(ind in text.lower() for ind in ['explain', 'analyze', 'compare', 'describe', 'how does', 'why does', 'what happens when', 'can you help me understand', 'walk me through']):
            return "complex"
        return "medium" if wc <= 15 else "complex"

    def _get_target_latency(self, complexity: str) -> int:
        return {"simple": self.SIMPLE_RESPONSE_MAX_MS, "medium": self.NORMAL_RESPONSE_MAX_MS // 2, "complex": self.NORMAL_RESPONSE_MAX_MS}.get(complexity, self.NORMAL_RESPONSE_MAX_MS)

    async def _generate_timed_response(self, session_id: str, room_name: str, text: str, complexity: str, target_latency_ms: int, start_time: float) -> Dict[str, Any]:
        state = self.active_conversations[session_id]
        state.is_ai_speaking = True
        preprocessed_key = f"preprocess:{session_id}"
        try:
            _ = await self.redis.get(preprocessed_key)
        except Exception as e:
            logger.debug(f"Preprocess fetch skipped: {e}")
        phrase_count = 0
        async def phrase_tts_callback(phrase: str):
            nonlocal phrase_count
            phrase_count += 1
            try:
                await self.tts.publish_to_room(room_name=room_name, text=phrase, language="en", speed=1.0)
            except Exception as e:
                logger.warning(f"Phrase TTS failed: {e}")
        try:
            if complexity == "complex" and target_latency_ms > 400:
                await phrase_tts_callback(self.hesitation_patterns["complex"][0])
                await asyncio.sleep(0.3)
            from ..core.dependencies import get_conversation_processor
            processor = get_conversation_processor()
            history = processor.session_service.get_history(session_id)
            full_tokens = []
            first_phrase_sent = False
            async for token in self.streaming_ai.generate_streaming_response(text=text, conversation_history=history, user_id="user", session_id=session_id, tts_callback=phrase_tts_callback):
                full_tokens.append(token)
                if not first_phrase_sent and phrase_count > 0:
                    first_phrase_time = (time.time() - start_time) * 1000
                    logger.info(f"⚡ First phrase spoken in {first_phrase_time:.0f}ms (target: {target_latency_ms}ms)")
                    first_phrase_sent = True
            total_time = (time.time() - start_time) * 1000
            response_text = "".join(full_tokens)
            await asyncio.sleep(self.TURN_TAKING_PAUSE_MS / 1000)
            state.is_ai_speaking = False
            state.last_ai_response_time = datetime.utcnow()
            return {"response": response_text, "phrases_sent": phrase_count, "total_time_ms": total_time, "first_phrase_time_ms": first_phrase_time if first_phrase_sent else total_time, "complexity": complexity, "target_met": (first_phrase_time <= target_latency_ms) if first_phrase_sent else False}
        except asyncio.CancelledError:
            logger.info(f"🛑 Response generation cancelled (interruption): {session_id}")
            state.is_ai_speaking = False
            raise
        except Exception as e:
            logger.error(f"❌ Response generation failed: {e}")
            state.is_ai_speaking = False
            await phrase_tts_callback("I'm sorry, I had a technical issue. Can you try again?")
            return {"error": str(e), "phrases_sent": 1}

    async def handle_voice_onset(self, session_id: str, room_name: str) -> Dict[str, Any]:
        state = self.active_conversations.get(session_id)
        if not state: return {"handled": False, "reason": "no_active_session"}
        if not state.is_ai_speaking: return {"handled": False, "reason": "ai_not_speaking"}
        if state.current_ai_task and not state.current_ai_task.done():
            state.current_ai_task.cancel()
        await self._stop_tts_in_room(room_name)
        state.is_ai_speaking = False
        state.is_user_speaking = True
        state.pending_interruption = True
        return {"handled": True, "acknowledged": True, "session_id": session_id, "interruption_time": datetime.utcnow().isoformat()}

    async def _stop_tts_in_room(self, room_name: str):
        try:
            logger.info(f"🔇 TTS stop requested for room: {room_name}")
        except Exception as e:
            logger.warning(f"TTS stop failed: {e}")

    def get_conversation_stats(self, session_id: str) -> Dict[str, Any]:
        state = self.active_conversations.get(session_id)
        if not state: return {"active": False}
        return {"active": True, "session_id": session_id, "is_ai_speaking": state.is_ai_speaking, "is_user_speaking": state.is_user_speaking, "turn_count": state.turn_count, "last_interaction": state.last_user_input_time.isoformat() if state.last_user_input_time else None, "conversation_complexity": state.conversation_complexity, "has_pending_interruption": state.pending_interruption}

    def get_global_stats(self) -> Dict[str, Any]:
        active_sessions = len(self.active_conversations)
        speaking_sessions = sum(1 for s in self.active_conversations.values() if s.is_ai_speaking)
        return {"active_conversations": active_sessions, "ai_currently_speaking": speaking_sessions, "engine_type": "real_time_sota", "target_latencies": {"simple_ms": self.SIMPLE_RESPONSE_MAX_MS, "normal_ms": self.NORMAL_RESPONSE_MAX_MS, "phrase_tokens": self.PHRASE_MIN_TOKENS, "token_gap_ms": self.TOKEN_GAP_THRESHOLD_MS}}
