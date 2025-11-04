"""Real-Time Engine - Simplified, No Redis Preprocessing

REMOVED:
- Redis preprocessing (causing failures)
- Complex conversation state tracking
- Unnecessary context building
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
        
        # Simple session tracking (no Redis)
        self.active_sessions: Dict[str, Dict] = {}
        
        # Initialize SmartTTSQueue
        self.smart_tts = None
        self._initialize_smart_tts_queue()
        
        logger.info("✅ RT engine initialized (Redis-free, simplified)")
    
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
            else:
                logger.warning("⚠️ No TTS service")
                
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
        """Main entry point - simplified flow"""
        start = time.time()
        
        # Skip partials for now (can add back later if needed)
        if is_partial:
            return {"processed": "partial_skipped"}
        
        # Track session
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "room_name": room_name,
                "history": []
            }
        
        session = self.active_sessions[session_id]
        
        # Add to simple history
        session["history"].append({"role": "user", "content": text})
        
        # Keep only last 10 messages
        if len(session["history"]) > 10:
            session["history"] = session["history"][-10:]
        
        # Get history for AI
        history = session["history"]
        
        # Track phrases
        phrase_count = 0
        first_phrase_sent = False
        
        async def smart_tts_callback(phrase: str):
            """TTS callback"""
            nonlocal phrase_count, first_phrase_sent
            phrase_count += 1
            is_first = not first_phrase_sent
            
            if is_first:
                first_phrase_sent = True
            
            try:
                if self.smart_tts:
                    await self.smart_tts.queue_phrase(
                        text=phrase,
                        room_name=room_name,
                        session_id=session_id,
                        is_first_phrase=is_first,
                        is_final=(phrase_count >= 3),
                        language="en"
                    )
                else:
                    await self.tts.publish_to_room(
                        room_name=room_name,
                        text=phrase,
                        language="en"
                    )
            except Exception as e:
                logger.warning(f"TTS callback error: {e}")
        
        # Generate AI response
        try:
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
            
            response_text = "".join(tokens)
            total = (time.time() - start) * 1000
            
            # Add AI response to history
            session["history"].append({"role": "assistant", "content": response_text})
            
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
        if session_id not in self.active_sessions:
            return {"active": False}
        
        session = self.active_sessions[session_id]
        stats = {
            "active": True,
            "message_count": len(session.get("history", []))
        }
        
        if self.smart_tts:
            stats["tts_queue"] = self.smart_tts.get_session_stats(session_id)
        
        return stats
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get global stats"""
        stats = {
            "active_sessions": len(self.active_sessions),
            "engine": "simplified_rt",
            "redis_free": True
        }
        
        if self.smart_tts:
            stats["smart_tts"] = self.smart_tts.get_global_stats()
        
        return stats
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check"""
        return {
            "engine_healthy": True,
            "active_sessions": len(self.active_sessions),
            "tts_available": self.tts is not None,
            "streaming_ai_available": self.streaming_ai is not None,
            "smart_tts_enabled": self.smart_tts is not None
        }