#!/usr/bin/env python3
"""Smart TTS Queue - XTTS Voice Integration"""
import asyncio
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class TTSPhrase:
    """TTS phrase with XTTS voice_id"""
    text: str
    room_name: str
    priority: int
    timestamp: datetime
    session_id: str
    voice_id: str = "default"  # ✅ CHANGED: voice_id instead of language
    synthesis_task: Optional[asyncio.Task] = field(default=None, init=False)
    audio_ready: Optional[asyncio.Event] = field(default=None, init=False)

class SmartTTSQueue:
    """Intelligent TTS queue with XTTS voice support"""
    
    def __init__(self, tts_service, max_concurrent: int = 2, phrase_gap_ms: int = 50):
        self.tts_service = tts_service
        self.max_concurrent = max_concurrent
        self.phrase_gap_ms = phrase_gap_ms
        self.active_sessions: Dict[str, List[TTSPhrase]] = {}
        self.synthesis_semaphore = asyncio.Semaphore(max_concurrent)
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self.session_playback_locks: Dict[str, asyncio.Lock] = {}
        self.metrics = {
            "phrases_queued": 0,
            "phrases_processed": 0,
            "urgent_phrases": 0,
            "interrupted_sessions": 0,
            "avg_first_phrase_ms": 0,
            "active_sessions": 0,
            "parallel_syntheses": 0
        }
        logger.info(f"🎵 SmartTTSQueue (XTTS): max_concurrent={max_concurrent}, phrase_gap={phrase_gap_ms}ms")

    async def queue_phrase(
        self, 
        text: str, 
        room_name: str, 
        session_id: str,
        is_first_phrase: bool = False,
        is_final: bool = False,
        voice_id: str = "default"  # ✅ CHANGED: voice_id parameter
    ) -> bool:
        try:
            if not text or len(text.strip()) == 0:
                return False
            
            if session_id not in self.session_locks:
                self.session_locks[session_id] = asyncio.Lock()
                self.session_playback_locks[session_id] = asyncio.Lock()
            
            priority = 1 if is_first_phrase else (3 if is_final else 2)
            
            phrase = TTSPhrase(
                text=text,
                room_name=room_name,
                priority=priority,
                timestamp=datetime.utcnow(),
                session_id=session_id,
                voice_id=voice_id  # ✅ CHANGED
            )
            phrase.audio_ready = asyncio.Event()
            
            async with self.session_locks[session_id]:
                if session_id not in self.active_sessions:
                    self.active_sessions[session_id] = []
                self.active_sessions[session_id].append(phrase)
            
            self.metrics["phrases_queued"] += 1
            
            if is_first_phrase:
                self.metrics["urgent_phrases"] += 1
                phrase.synthesis_task = asyncio.create_task(self._synthesize_phrase(phrase))
                asyncio.create_task(self._process_phrase_urgent(phrase))
                logger.info(f"🚀 URGENT TTS queued: '{text[:30]}...' voice={voice_id}")
            else:
                phrase.synthesis_task = asyncio.create_task(self._synthesize_phrase(phrase))
                asyncio.create_task(self._process_phrase_sequential(phrase, session_id))
                logger.info(f"📋 QUEUED TTS: '{text[:30]}...' voice={voice_id}")
            
            return True
        except Exception as e:
            logger.error(f"❌ Failed to queue phrase: {e}")
            return False

    async def _synthesize_phrase(self, phrase: TTSPhrase) -> bool:
        """Synthesize audio using XTTS"""
        try:
            async with self.synthesis_semaphore:
                logger.info(f"🔊 Synthesizing: '{phrase.text[:30]}...' voice={phrase.voice_id}")
                self.metrics["parallel_syntheses"] += 1
                
                success = await self.tts_service.publish_to_room(
                    room_name=phrase.room_name,
                    text=phrase.text,
                    voice_id=phrase.voice_id,  # ✅ CHANGED
                    streaming=True
                )
                
                if success:
                    phrase.audio_ready.set()
                    logger.info(f"✅ Synthesis complete: '{phrase.text[:30]}...'")
                    return True
                else:
                    logger.error(f"❌ Synthesis failed: '{phrase.text[:30]}...'")
                    phrase.audio_ready.set()
                    return False
        except Exception as e:
            logger.error(f"❌ Synthesis error: {e}")
            phrase.audio_ready.set()
            return False

    async def _process_phrase_urgent(self, phrase: TTSPhrase):
        """Process urgent (first) phrase"""
        start_time = asyncio.get_event_loop().time()
        try:
            await phrase.audio_ready.wait()
            elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self.metrics["phrases_processed"] += 1
            logger.info(f"✅ URGENT TTS completed: {elapsed_ms:.0f}ms")
            
            if self.metrics["avg_first_phrase_ms"] == 0:
                self.metrics["avg_first_phrase_ms"] = elapsed_ms
            else:
                self.metrics["avg_first_phrase_ms"] = (
                    self.metrics["avg_first_phrase_ms"] * 0.8 + elapsed_ms * 0.2
                )
        except Exception as e:
            logger.error(f"❌ Urgent TTS error: {e}")
        finally:
            await self._remove_phrase_from_session(phrase)

    async def _process_phrase_sequential(self, phrase: TTSPhrase, session_id: str):
        """Process sequential phrase"""
        try:
            async with self.session_playback_locks[session_id]:
                await asyncio.sleep(self.phrase_gap_ms / 1000.0)
                await phrase.audio_ready.wait()
                self.metrics["phrases_processed"] += 1
                logger.info(f"✅ SEQUENTIAL TTS completed: '{phrase.text[:30]}...'")
        except Exception as e:
            logger.error(f"❌ Sequential TTS error: {e}")
        finally:
            await self._remove_phrase_from_session(phrase)

    async def _remove_phrase_from_session(self, phrase: TTSPhrase):
        try:
            session_id = phrase.session_id
            if session_id in self.session_locks and session_id in self.active_sessions:
                async with self.session_locks[session_id]:
                    self.active_sessions[session_id] = [
                        p for p in self.active_sessions[session_id] 
                        if p.timestamp != phrase.timestamp
                    ]
                    if not self.active_sessions[session_id]:
                        del self.active_sessions[session_id]
                        if session_id in self.session_locks:
                            del self.session_locks[session_id]
                        if session_id in self.session_playback_locks:
                            del self.session_playback_locks[session_id]
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    async def interrupt_session(self, session_id: str) -> Dict[str, Any]:
        try:
            if session_id not in self.active_sessions:
                return {"interrupted": False, "cleared_phrases": 0}
            
            async with self.session_locks[session_id]:
                pending_phrases = self.active_sessions[session_id]
                pending_count = len(pending_phrases)
                
                for phrase in pending_phrases:
                    if phrase.synthesis_task and not phrase.synthesis_task.done():
                        phrase.synthesis_task.cancel()
                
                self.active_sessions[session_id].clear()
                self.metrics["interrupted_sessions"] += 1
                logger.info(f"🛑 Interrupted {session_id}: cleared {pending_count} phrases")
                
                return {
                    "interrupted": True,
                    "cleared_phrases": pending_count,
                    "session_id": session_id
                }
        except Exception as e:
            logger.error(f"Interrupt failed: {e}")
            return {"interrupted": False, "error": str(e)}

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.active_sessions:
            return {"queued_phrases": 0, "status": "idle"}
        
        phrases = self.active_sessions[session_id]
        synthesizing = sum(1 for p in phrases if p.synthesis_task and not p.synthesis_task.done())
        
        return {
            "queued_phrases": len(phrases),
            "synthesizing": synthesizing,
            "next_priority": min(p.priority for p in phrases) if phrases else None,
            "status": "active" if phrases else "idle"
        }

    def get_global_stats(self) -> Dict[str, Any]:
        self.metrics["active_sessions"] = len(self.active_sessions)
        total_queued = sum(len(phrases) for phrases in self.active_sessions.values())
        
        return {
            **self.metrics,
            "total_queued_phrases": total_queued,
            "sessions_with_pending": len([s for s in self.active_sessions.values() if s]),
            "synthesis_slots_available": self.synthesis_semaphore._value,
            "phrase_gap_ms": self.phrase_gap_ms,
            "max_concurrent": self.max_concurrent,
            "queue_type": "xtts_smart_queue"
        }

    async def health_check(self) -> Dict[str, Any]:
        try:
            tts_healthy = await self.tts_service.health_check()
            return {
                "queue_healthy": True,
                "tts_service_healthy": tts_healthy,
                "active_sessions": len(self.active_sessions),
                "synthesis_capacity": self.synthesis_semaphore._value,
                "metrics": self.get_global_stats()
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "queue_healthy": False,
                "error": str(e),
                "tts_service_healthy": False
            }


smart_tts_queue: Optional[SmartTTSQueue] = None

def initialize_smart_tts_queue(tts_service, max_concurrent: int = 2, phrase_gap_ms: int = 50):
    global smart_tts_queue
    smart_tts_queue = SmartTTSQueue(tts_service, max_concurrent, phrase_gap_ms)
    logger.info("🎵 Global SmartTTSQueue initialized (XTTS)")
    return smart_tts_queue

def get_smart_tts_queue() -> Optional[SmartTTSQueue]:
    return smart_tts_queue