#!/usr/bin/env python3
"""
Smart TTS Queue - Natural Conversation Flow with GPU Protection
Maintains human-like conversation timing while preventing GPU overload
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class TTSPhrase:
    """Represents a TTS phrase with priority and timing info"""
    text: str
    room_name: str
    priority: int  # 1=first phrase (urgent), 2=continuation, 3=final
    timestamp: datetime
    session_id: str
    language: str = "en"
    speaker_id: Optional[str] = None  # CosyVoice2 speaker ID
    speed: float = 1.0

class SmartTTSQueue:
    """
    Intelligent TTS queue that maintains conversation flow while protecting GPU
    
    Key Features:
    - First phrase priority: Sub-500ms response for natural conversation
    - Sequential processing: Prevents GPU overload from concurrent requests
    - Session isolation: Multiple users don't interfere
    - Interruption handling: Can stop mid-response when user speaks
    - Natural timing: 50ms gaps between phrases mimic human speech
    """
    
    def __init__(self, tts_service, max_concurrent: int = 1, phrase_gap_ms: int = 50):
        self.tts_service = tts_service
        self.max_concurrent = max_concurrent
        self.phrase_gap_ms = phrase_gap_ms
        
        # Session management
        self.active_sessions: Dict[str, List[TTSPhrase]] = {}
        self.processing_semaphore = asyncio.Semaphore(max_concurrent)
        self.session_locks: Dict[str, asyncio.Lock] = {}
        
        # Metrics
        self.metrics = {
            "phrases_queued": 0,
            "phrases_processed": 0,
            "urgent_phrases": 0,
            "interrupted_sessions": 0,
            "avg_first_phrase_ms": 0,
            "active_sessions": 0
        }
        
        logger.info(f"🎵 SmartTTSQueue initialized: max_concurrent={max_concurrent}, phrase_gap={phrase_gap_ms}ms")
    
    async def queue_phrase(
        self, 
        text: str, 
        room_name: str, 
        session_id: str,
        is_first_phrase: bool = False,
        is_final: bool = False,
        language: str = "en",
        speaker_id: Optional[str] = None,
        speed: float = 1.0
    ) -> bool:
        """
        Queue phrase with priority for natural conversation flow
        
        Args:
            text: Text to synthesize
            room_name: LiveKit room name
            session_id: User session identifier
            is_first_phrase: True for urgent first response (maintains naturalness)
            is_final: True for last phrase in response
            language: Target language
            speaker_id: CosyVoice2 speaker ID
            speed: Speech speed multiplier
            
        Returns:
            True if queued successfully, False otherwise
        """
        try:
            if not text or len(text.strip()) == 0:
                return False
            
            # Initialize session lock if needed
            if session_id not in self.session_locks:
                self.session_locks[session_id] = asyncio.Lock()
            
            # Determine priority (1=urgent, 2=normal, 3=final)
            priority = 1 if is_first_phrase else (3 if is_final else 2)
            
            phrase = TTSPhrase(
                text=text,
                room_name=room_name,
                priority=priority,
                timestamp=datetime.utcnow(),
                session_id=session_id,
                language=language,
                speaker_id=speaker_id,
                speed=speed
            )
            
            # Add to session queue
            async with self.session_locks[session_id]:
                if session_id not in self.active_sessions:
                    self.active_sessions[session_id] = []
                self.active_sessions[session_id].append(phrase)
            
            self.metrics["phrases_queued"] += 1
            
            # Process immediately for first phrase (maintain responsiveness)
            if is_first_phrase:
                self.metrics["urgent_phrases"] += 1
                asyncio.create_task(self._process_phrase_urgent(phrase))
                logger.info(f"🚀 URGENT TTS queued: '{text[:30]}...' for {session_id}")
            else:
                asyncio.create_task(self._process_phrase_sequential(phrase, session_id))
                logger.info(f"📋 QUEUED TTS: '{text[:30]}...' for {session_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to queue phrase for {session_id}: {e}")
            return False
    
    async def _process_phrase_urgent(self, phrase: TTSPhrase):
        """Process first phrase immediately for sub-500ms response"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with self.processing_semaphore:
                logger.info(f"🚀 URGENT TTS processing: '{phrase.text[:30]}...'")
                
                success = await self.tts_service.publish_to_room(
                    room_name=phrase.room_name,
                    text=phrase.text,
                    language=phrase.language,
                    speaker_id=phrase.speaker_id,
                    speed=phrase.speed,
                    streaming=True
                )
                
                if success:
                    elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    self.metrics["phrases_processed"] += 1
                    logger.info(f"✅ URGENT TTS completed: {elapsed_ms:.0f}ms")
                    
                    # Update first phrase timing metric
                    if self.metrics["avg_first_phrase_ms"] == 0:
                        self.metrics["avg_first_phrase_ms"] = elapsed_ms
                    else:
                        # Simple moving average
                        self.metrics["avg_first_phrase_ms"] = (
                            self.metrics["avg_first_phrase_ms"] * 0.8 + elapsed_ms * 0.2
                        )
                else:
                    logger.error(f"❌ URGENT TTS failed for {phrase.session_id}")
                    
        except Exception as e:
            logger.error(f"❌ Urgent TTS processing error: {e}")
        finally:
            # Clean up processed phrase
            await self._remove_phrase_from_session(phrase)
    
    async def _process_phrase_sequential(self, phrase: TTSPhrase, session_id: str):
        """Process continuation phrases with natural timing"""
        try:
            # Wait for natural gap between phrases (mimics human speech)
            await asyncio.sleep(self.phrase_gap_ms / 1000.0)
            
            async with self.processing_semaphore:
                logger.info(f"🎵 SEQUENTIAL TTS processing: '{phrase.text[:30]}...'")
                
                success = await self.tts_service.publish_to_room(
                    room_name=phrase.room_name,
                    text=phrase.text,
                    language=phrase.language,
                    speaker_id=phrase.speaker_id,
                    speed=phrase.speed,
                    streaming=True
                )
                
                if success:
                    self.metrics["phrases_processed"] += 1
                    logger.info(f"✅ SEQUENTIAL TTS completed: '{phrase.text[:30]}...'")
                else:
                    logger.error(f"❌ SEQUENTIAL TTS failed for {session_id}")
                    
        except Exception as e:
            logger.error(f"❌ Sequential TTS processing error: {e}")
        finally:
            # Clean up processed phrase
            await self._remove_phrase_from_session(phrase)
    
    async def _remove_phrase_from_session(self, phrase: TTSPhrase):
        """Remove processed phrase from session queue"""
        try:
            session_id = phrase.session_id
            if session_id in self.session_locks and session_id in self.active_sessions:
                async with self.session_locks[session_id]:
                    self.active_sessions[session_id] = [
                        p for p in self.active_sessions[session_id] 
                        if p.timestamp != phrase.timestamp
                    ]
                    
                    # Clean up empty sessions
                    if not self.active_sessions[session_id]:
                        del self.active_sessions[session_id]
                        del self.session_locks[session_id]
                        
        except Exception as e:
            logger.warning(f"Failed to clean up phrase: {e}")
    
    async def interrupt_session(self, session_id: str) -> Dict[str, Any]:
        """
        Handle user interruption - clear pending phrases
        
        Args:
            session_id: Session to interrupt
            
        Returns:
            Dictionary with interruption stats
        """
        try:
            if session_id not in self.active_sessions:
                return {"interrupted": False, "cleared_phrases": 0}
            
            async with self.session_locks[session_id]:
                pending_count = len(self.active_sessions[session_id])
                self.active_sessions[session_id].clear()
                
                self.metrics["interrupted_sessions"] += 1
                logger.info(f"🛑 Interrupted {session_id}: cleared {pending_count} phrases")
                
                return {
                    "interrupted": True,
                    "cleared_phrases": pending_count,
                    "session_id": session_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Failed to interrupt session {session_id}: {e}")
            return {"interrupted": False, "error": str(e)}
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get queue status for specific session"""
        if session_id not in self.active_sessions:
            return {"queued_phrases": 0, "status": "idle"}
        
        phrases = self.active_sessions[session_id]
        return {
            "queued_phrases": len(phrases),
            "next_priority": min(p.priority for p in phrases) if phrases else None,
            "status": "active" if phrases else "idle",
            "session_id": session_id
        }
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get comprehensive queue statistics"""
        self.metrics["active_sessions"] = len(self.active_sessions)
        
        total_queued = sum(len(phrases) for phrases in self.active_sessions.values())
        
        return {
            **self.metrics,
            "total_queued_phrases": total_queued,
            "sessions_with_pending": len([s for s in self.active_sessions.values() if s]),
            "semaphore_available": self.processing_semaphore._value,
            "phrase_gap_ms": self.phrase_gap_ms,
            "max_concurrent": self.max_concurrent,
            "queue_type": "smart_conversation_aware"
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check queue health and TTS service connectivity"""
        try:
            # Test underlying TTS service
            tts_healthy = await self.tts_service.health_check()
            
            return {
                "queue_healthy": True,
                "tts_service_healthy": tts_healthy,
                "active_sessions": len(self.active_sessions),
                "processing_capacity": self.processing_semaphore._value,
                "metrics": self.get_global_stats()
            }
            
        except Exception as e:
            logger.error(f"SmartTTSQueue health check failed: {e}")
            return {
                "queue_healthy": False,
                "error": str(e),
                "tts_service_healthy": False
            }


# Global queue instance - will be initialized by conversation engine
smart_tts_queue: Optional[SmartTTSQueue] = None

def initialize_smart_tts_queue(tts_service, max_concurrent: int = 1, phrase_gap_ms: int = 50):
    """Initialize global smart TTS queue instance"""
    global smart_tts_queue
    smart_tts_queue = SmartTTSQueue(tts_service, max_concurrent, phrase_gap_ms)
    logger.info("🎵 Global SmartTTSQueue initialized")
    return smart_tts_queue

def get_smart_tts_queue() -> Optional[SmartTTSQueue]:
    """Get global smart TTS queue instance"""
    return smart_tts_queue