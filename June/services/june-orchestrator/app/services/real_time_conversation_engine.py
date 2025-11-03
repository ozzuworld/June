# Real-Time Conversation Engine - SOTA Natural Flow Implementation
# Enhanced with SmartTTSQueue for GPU-safe natural conversation

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
        
        # Conversation timing constants (research-based)
        self.SIMPLE_RESPONSE_MAX_MS = 200
        self.NORMAL_RESPONSE_MAX_MS = 800
        self.PHRASE_MIN_TOKENS = 4
        self.TOKEN_GAP_THRESHOLD_MS = 80
        self.INTERRUPTION_DETECT_MS = 200
        self.TURN_TAKING_PAUSE_MS = 150
        
        # Initialize SmartTTSQueue for natural conversation flow
        self.smart_tts = None
        self._initialize_smart_tts_queue()

    def _initialize_smart_tts_queue(self):
        """Initialize SmartTTSQueue with conversation-aware settings"""
        try:
            from .smart_tts_queue import initialize_smart_tts_queue
            
            if self.tts:
                # GPU-safe settings: 1 concurrent, 50ms natural gaps
                self.smart_tts = initialize_smart_tts_queue(
                    tts_service=self.tts,
                    max_concurrent=1,  # Protect single GPU
                    phrase_gap_ms=50   # Natural conversation timing
                )
                logger.info("🎵 SmartTTSQueue integrated with RealTimeConversationEngine")
            else:
                logger.warning("⚠️ TTS service not available, using fallback mode")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize SmartTTSQueue: {e}")
            logger.info("📢 Falling back to direct TTS mode")

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
        
        # Handle partial input (preprocessing)
        if is_partial:
            if len(text.split()) >= 3 and text.endswith(('.', '?', '!')):
                if not state.current_ai_task or state.current_ai_task.done():
                    state.current_ai_task = asyncio.create_task(self._preprocess_ai_response(session_id, room_name, session_id, text))
            return {"processed": "partial"}
        
        # Get conversation history
        history = await self._get_history(room_name, session_id)
        
        # Initialize phrase tracking for natural conversation
        phrase_count = 0
        first_phrase_sent = False
        
        async def smart_tts_callback(phrase: str):
            """Intelligent TTS callback using SmartTTSQueue"""
            nonlocal phrase_count, first_phrase_sent
            phrase_count += 1
            
            is_first = not first_phrase_sent
            if is_first:
                first_phrase_sent = True
            
            try:
                if self.smart_tts:
                    # Use SmartTTSQueue for natural conversation flow
                    await self.smart_tts.queue_phrase(
                        text=phrase,
                        room_name=room_name,
                        session_id=session_id,
                        is_first_phrase=is_first,
                        is_final=(phrase_count >= 3),  # Estimate final phrase
                        language="en"
                    )
                else:
                    # Fallback to direct TTS if SmartTTSQueue unavailable
                    await self.tts.publish_to_room(room_name=room_name, text=phrase, language="en")
                    
            except Exception as e:
                logger.warning(f"Smart TTS callback error: {e}")
                # Final fallback
                try:
                    await self.tts.publish_to_room(room_name=room_name, text=phrase, language="en")
                except Exception as fallback_e:
                    logger.error(f"TTS fallback failed: {fallback_e}")
        
        # Generate streaming AI response with smart TTS
        try:
            from ..services.ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, history, session_id)
            first_phrase_time = None
            tokens = []
            
            async for token in self.streaming_ai.generate_streaming_response(
                text=text, 
                conversation_history=history, 
                user_id=session_id, 
                session_id=session_id, 
                tts_callback=smart_tts_callback
            ):
                tokens.append(token)
                if first_phrase_time is None and phrase_count > 0:
                    first_phrase_time = (time.time() - start) * 1000
            
            total = (time.time() - start) * 1000
            
            # Enhanced response metrics
            response_data = {
                "response": "".join(tokens),
                "phrases_sent": phrase_count,
                "total_time_ms": total,
                "first_phrase_time_ms": first_phrase_time or total,
                "complexity": "medium",
                "target_met": (first_phrase_time or total) <= 800,
                "smart_tts_enabled": self.smart_tts is not None,
                "natural_flow": True
            }
            
            # Add SmartTTSQueue stats if available
            if self.smart_tts:
                response_data["queue_stats"] = self.smart_tts.get_session_stats(session_id)
            
            return response_data
            
        except Exception as e:
            logger.error(f"RT engine failed: {e}")
            # Emergency fallback response
            await smart_tts_callback("I'm sorry, I had a technical issue. Can you try again?")
            return {"error": str(e)}

    async def handle_voice_onset(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """Handle user interruption - stop current AI response"""
        try:
            # Interrupt current TTS if using SmartTTSQueue
            if self.smart_tts:
                interrupt_result = await self.smart_tts.interrupt_session(session_id)
                logger.info(f"🛑 Voice onset: interrupted {session_id}, cleared {interrupt_result.get('cleared_phrases', 0)} phrases")
                return {
                    "handled": True, 
                    "session_id": session_id, 
                    "time": datetime.utcnow().isoformat(),
                    "interrupt_result": interrupt_result
                }
            else:
                # Fallback behavior
                return {"handled": True, "session_id": session_id, "time": datetime.utcnow().isoformat()}
                
        except Exception as e:
            logger.error(f"Voice onset handling failed: {e}")
            return {"handled": False, "error": str(e)}

    def get_conversation_stats(self, session_id: str) -> Dict[str, Any]:
        """Get comprehensive conversation statistics"""
        state = self.active_conversations.get(session_id)
        base_stats = {"active": bool(state), "session_id": session_id}
        
        # Add SmartTTSQueue stats if available
        if self.smart_tts:
            base_stats["tts_queue"] = self.smart_tts.get_session_stats(session_id)
        
        # Add conversation state details
        if state:
            base_stats.update({
                "is_ai_speaking": state.is_ai_speaking,
                "is_user_speaking": state.is_user_speaking,
                "turn_count": state.turn_count,
                "complexity": state.conversation_complexity
            })
        
        return base_stats

    def get_global_stats(self) -> Dict[str, Any]:
        """Get comprehensive global statistics"""
        base_stats = {
            "active_conversations": len(self.active_conversations), 
            "engine_type": "real_time_sota_with_smart_tts",
            "smart_tts_enabled": self.smart_tts is not None
        }
        
        # Add SmartTTSQueue global stats if available
        if self.smart_tts:
            base_stats["smart_tts_stats"] = self.smart_tts.get_global_stats()
        
        return base_stats
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check including SmartTTSQueue"""
        try:
            health_data = {
                "engine_healthy": True,
                "active_conversations": len(self.active_conversations),
                "redis_connected": self.redis is not None,
                "tts_service_available": self.tts is not None,
                "streaming_ai_available": self.streaming_ai is not None,
                "smart_tts_enabled": self.smart_tts is not None
            }
            
            # Check SmartTTSQueue health if available
            if self.smart_tts:
                smart_tts_health = await self.smart_tts.health_check()
                health_data["smart_tts_health"] = smart_tts_health
            
            return health_data
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"engine_healthy": False, "error": str(e)}