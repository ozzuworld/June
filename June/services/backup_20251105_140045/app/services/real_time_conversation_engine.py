"""Real-Time Engine - ULTRA FAST - Remove ALL blocking operations

PROBLEM FOUND: Session history lookup was blocking for 2+ seconds
SOLUTION: Remove session service dependency, use in-memory only
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

class RealTimeConversationEngine:
    def __init__(self, redis_client=None, tts_service=None, streaming_ai_service=None):
        self.tts = tts_service
        self.streaming_ai = streaming_ai_service
        
        # Ultra-simple in-memory history (no external calls)
        self.session_history: Dict[str, List[Dict]] = {}
        
        # Initialize SmartTTSQueue
        self.smart_tts = None
        self._initialize_smart_tts_queue()
        
        logger.info("✅ RT engine initialized (ULTRA FAST mode)")
    
    def _initialize_smart_tts_queue(self):
        """Initialize SmartTTSQueue"""
        try:
            from .smart_tts_queue import initialize_smart_tts_queue
            
            if self.tts:
                self.smart_tts = initialize_smart_tts_queue(
                    tts_service=self.tts,
                    max_concurrent=1,
                    phrase_gap_ms=50
                )
                logger.info("🎵 SmartTTSQueue ready")
        except Exception as e:
            logger.error(f"❌ SmartTTSQueue init failed: {e}")
    
    async def handle_user_input(
        self,
        session_id: str,
        room_name: str,
        text: str,
        audio_data: Optional[bytes] = None,
        is_partial: bool = False
    ) -> Dict[str, Any]:
        """ULTRA FAST - No blocking operations"""
        start = time.time()
        
        # Skip partials
        if is_partial:
            return {"processed": "partial_skipped"}
        
        logger.info(f"🚀 Processing '{text[:30]}...' for {session_id}")
        
        # ULTRA FAST: Get history from memory (no I/O)
        if session_id not in self.session_history:
            self.session_history[session_id] = []
        
        history = self.session_history[session_id]
        
        # Add user message (instant)
        history.append({"role": "user", "content": text})
        
        # Keep only last 6 messages (3 exchanges)
        if len(history) > 6:
            self.session_history[session_id] = history[-6:]
            history = self.session_history[session_id]
        
        logger.info(f"📝 History: {len(history)} messages (instant)")
        
        # Track phrases
        phrase_count = 0
        first_phrase_sent = False
        first_phrase_time = None
        
        async def smart_tts_callback(phrase: str):
            """TTS callback"""
            nonlocal phrase_count, first_phrase_sent, first_phrase_time
            phrase_count += 1
            
            if not first_phrase_sent:
                first_phrase_sent = True
                first_phrase_time = (time.time() - start) * 1000
                logger.info(f"⚡ FIRST PHRASE at {first_phrase_time:.0f}ms")
            
            try:
                if self.smart_tts:
                    await self.smart_tts.queue_phrase(
                        text=phrase,
                        room_name=room_name,
                        session_id=session_id,
                        is_first_phrase=(phrase_count == 1),
                        is_final=(phrase_count >= 3),
                        language="en",
                        speaker_id=None  # Will use default
                    )
                else:
                    await self.tts.publish_to_room(
                        room_name=room_name,
                        text=phrase,
                        language="en",
                        streaming=True
                    )
            except Exception as e:
                logger.warning(f"TTS callback error: {e}")
        
        # Generate AI response (this should be INSTANT start now)
        try:
            logger.info(f"🧠 Starting AI stream (elapsed: {(time.time() - start) * 1000:.0f}ms)")
            
            tokens = []
            
            async for token in self.streaming_ai.generate_streaming_response(
                text=text,
                conversation_history=history,
                user_id=session_id,
                session_id=session_id,
                tts_callback=smart_tts_callback
            ):
                tokens.append(token)
            
            response_text = "".join(tokens)
            total = (time.time() - start) * 1000
            
            # Add AI response to history (instant)
            history.append({"role": "assistant", "content": response_text})
            
            logger.info(f"✅ Complete: {total:.0f}ms, {phrase_count} phrases")
            
            return {
                "response": response_text,
                "phrases_sent": phrase_count,
                "total_time_ms": total,
                "first_phrase_time_ms": first_phrase_time or total,
                "smart_tts_enabled": self.smart_tts is not None
            }
            
        except Exception as e:
            logger.error(f"RT engine error: {e}")
            # Fallback response
            fallback = "I'm sorry, I had a technical issue."
            await smart_tts_callback(fallback)
            return {"error": str(e), "response": fallback}
    
    async def handle_voice_onset(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """Handle interruption"""
        try:
            if self.smart_tts:
                result = await self.smart_tts.interrupt_session(session_id)
                logger.info(f"🛑 Interrupted {session_id}")
                return {"handled": True, "result": result}
            return {"handled": True}
        except Exception as e:
            logger.error(f"Interrupt failed: {e}")
            return {"handled": False, "error": str(e)}
    
    def get_conversation_stats(self, session_id: str) -> Dict[str, Any]:
        """Get session stats"""
        if session_id not in self.session_history:
            return {"active": False}
        
        stats = {
            "active": True,
            "message_count": len(self.session_history[session_id])
        }
        
        if self.smart_tts:
            stats["tts_queue"] = self.smart_tts.get_session_stats(session_id)
        
        return stats
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get global stats"""
        stats = {
            "active_sessions": len(self.session_history),
            "engine": "ultra_fast_rt",
            "in_memory_only": True
        }
        
        if self.smart_tts:
            stats["smart_tts"] = self.smart_tts.get_global_stats()
        
        return stats
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check"""
        return {
            "engine_healthy": True,
            "active_sessions": len(self.session_history),
            "tts_available": self.tts is not None,
            "streaming_ai_available": self.streaming_ai is not None,
            "smart_tts_enabled": self.smart_tts is not None,
            "mode": "ultra_fast_in_memory"
        }