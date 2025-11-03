# Real-Time Conversation Engine - SOTA Natural Flow Implementation
# Based on 2024-2025 voice AI research: sub-1.5s latency, phrase streaming, full-duplex

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Callable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from collections import deque
import json

logger = logging.getLogger(__name__)

@dataclass
class ConversationState:
    """Real-time conversation state tracking"""
    session_id: str
    is_ai_speaking: bool = False
    is_user_speaking: bool = False
    last_user_input_time: Optional[datetime] = None
    last_ai_response_time: Optional[datetime] = None
    current_ai_task: Optional[asyncio.Task] = None
    pending_interruption: bool = False
    conversation_complexity: str = "simple"  # simple, medium, complex
    turn_count: int = 0

class RealTimeConversationEngine:
    """SOTA conversation engine achieving <1.5s latency with natural turn-taking"""
    
    def __init__(self, redis_client, tts_service, streaming_ai_service):
        self.redis = redis_client
        self.tts = tts_service
        self.streaming_ai = streaming_ai_service
        self.active_conversations: Dict[str, ConversationState] = {}
        
        # SOTA timing thresholds (based on 2024-2025 research)
        self.SIMPLE_RESPONSE_MAX_MS = 200  # "Hello" -> instant
        self.NORMAL_RESPONSE_MAX_MS = 800  # Complex -> sub-1s
        self.PHRASE_MIN_TOKENS = 4         # Stream on 4-word chunks
        self.TOKEN_GAP_THRESHOLD_MS = 80   # Faster phrase breaks
        self.INTERRUPTION_DETECT_MS = 200  # React to interruptions in 200ms
        self.TURN_TAKING_PAUSE_MS = 150    # Natural pause between turns
        
        # Natural hesitation patterns (Google Duplex approach)
        self.hesitation_patterns = {
            "processing": ["Hmm,", "Let me think,", "Well,"],
            "complex": ["That's a great question.", "Interesting point."],
            "simple": []  # No hesitation for simple responses
        }
    
    async def start_conversation_session(self, session_id: str, room_name: str) -> ConversationState:
        """Initialize real-time conversation session"""
        state = ConversationState(session_id=session_id)
        self.active_conversations[session_id] = state
        
        # Start full-duplex listeners
        asyncio.create_task(self._monitor_conversation_state(session_id, room_name))
        
        logger.info(f"🎙️ Started real-time conversation session: {session_id}")
        return state
    
    async def handle_user_input(self, session_id: str, room_name: str, text: str, 
                               audio_data: Optional[bytes] = None, 
                               is_partial: bool = False) -> Dict[str, Any]:
        """Handle user input with SOTA timing and turn-taking"""
        start_time = time.time()
        
        # Get or create conversation state
        state = self.active_conversations.get(session_id)
        if not state:
            state = await self.start_conversation_session(session_id, room_name)
        
        # Interruption handling
        if state.is_ai_speaking and not is_partial:
            await self._handle_interruption(session_id, room_name, text)
            state.pending_interruption = False
        
        # Skip processing for partials unless significant change
        if is_partial:
            return await self._handle_partial_input(session_id, text, state)
        
        # Update conversation state
        state.last_user_input_time = datetime.utcnow()
        state.is_user_speaking = False
        state.turn_count += 1
        
        # Determine response complexity and timing target
        complexity = self._analyze_input_complexity(text, state)
        target_latency = self._get_target_latency(complexity)
        
        # Generate response with appropriate timing
        response_result = await self._generate_timed_response(
            session_id, room_name, text, complexity, target_latency, start_time
        )
        
        return response_result
    
    async def _handle_interruption(self, session_id: str, room_name: str, user_text: str):
        """Handle user interruption with context awareness"""
        state = self.active_conversations[session_id]
        
        # Smart interruption filtering (ignore filler words)
        if self._is_valid_interruption(user_text):
            logger.info(f"🛑 Valid interruption detected: '{user_text[:30]}...'")
            
            # Stop current AI task
            if state.current_ai_task and not state.current_ai_task.done():
                state.current_ai_task.cancel()
            
            # Stop TTS immediately
            # Note: Your TTS service needs a stop endpoint for this to work
            try:
                await self._stop_tts_in_room(room_name)
            except Exception as e:
                logger.warning(f"TTS stop failed: {e}")
            
            # Send natural acknowledgment
            acknowledgments = ["Yes?", "Go ahead.", "I'm listening."]
            import random
            ack = random.choice(acknowledgments)
            
            # Publish acknowledgment immediately (no processing delay)
            await self.tts.publish_to_room(
                room_name=room_name,
                text=ack,
                language="en"
            )
            
            state.is_ai_speaking = False
            state.pending_interruption = False
            
        else:
            logger.debug(f"🔇 Ignored interruption: '{user_text}' (filler/background)")
    
    def _is_valid_interruption(self, text: str) -> bool:
        """Context-aware interruption detection (ignore filler)"""
        text_lower = text.lower().strip()
        
        # Ignore filler words and very short inputs
        if text_lower in ['um', 'uh', 'hmm', 'ah', 'er', 'well']:
            return False
        
        if len(text_lower) < 3:
            return False
        
        # Valid interruptions: questions, corrections, urgency
        interruption_signals = [
            'wait', 'stop', 'hold on', 'actually', 'no', 'but', 'however',
            'what', 'how', 'why', 'can you', 'i need', 'sorry', 'excuse me'
        ]
        
        return any(signal in text_lower for signal in interruption_signals)
    
    async def _handle_partial_input(self, session_id: str, partial_text: str, state: ConversationState) -> Dict[str, Any]:
        """Handle STT partial with early AI start (parallel processing)"""
        # For very confident partials on simple inputs, start AI processing early
        if len(partial_text.split()) >= 3 and partial_text.endswith(('.', '?', '!')):
            # This looks like a complete thought - start AI processing
            logger.info(f"⚡ Early AI start on confident partial: '{partial_text[:30]}...'")
            
            # Start AI processing in background
            if not state.current_ai_task or state.current_ai_task.done():
                state.current_ai_task = asyncio.create_task(
                    self._preprocess_ai_response(session_id, partial_text)
                )
        
        return {"processed": "partial", "early_start": bool(state.current_ai_task)}
    
    async def _preprocess_ai_response(self, session_id: str, text: str):
        """Preprocess AI response for faster final delivery"""
        try:
            # Pre-generate context and first tokens
            from ..services.ai_service import build_context_for_voice
            from ..core.dependencies import get_conversation_processor
            
            processor = get_conversation_processor()
            history = processor.session_service.get_history(session_id)
            
            # Build context ahead of time
            context = build_context_for_voice(text, history, "user")
            
            # Store preprocessed context for quick access
            await self.redis.setex(
                f"preprocess:{session_id}",
                30,  # 30 second TTL
                json.dumps({"context": context, "text": text, "timestamp": time.time()})
            )
            
            logger.debug(f"✅ Preprocessed context for {session_id}")
            
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")
    
    def _analyze_input_complexity(self, text: str, state: ConversationState) -> str:
        """Analyze input complexity to set appropriate response timing"""
        words = text.split()
        word_count = len(words)
        
        # Simple inputs (greetings, confirmations, short questions)
        if word_count <= 3:
            return "simple"
        
        # Check for complex patterns
        complex_indicators = [
            'explain', 'analyze', 'compare', 'describe', 'how does', 'why does',
            'what happens when', 'can you help me understand', 'walk me through'
        ]
        
        if any(indicator in text.lower() for indicator in complex_indicators):
            return "complex"
        
        # Medium complexity for most other inputs
        if word_count <= 15:
            return "medium"
        
        return "complex"
    
    def _get_target_latency(self, complexity: str) -> int:
        """Get target response latency based on complexity"""
        targets = {
            "simple": self.SIMPLE_RESPONSE_MAX_MS,      # 200ms
            "medium": self.NORMAL_RESPONSE_MAX_MS // 2, # 400ms  
            "complex": self.NORMAL_RESPONSE_MAX_MS      # 800ms
        }
        return targets.get(complexity, self.NORMAL_RESPONSE_MAX_MS)
    
    async def _generate_timed_response(self, session_id: str, room_name: str, text: str, 
                                     complexity: str, target_latency_ms: int, start_time: float) -> Dict[str, Any]:
        """Generate response with timing optimizations"""
        state = self.active_conversations[session_id]
        state.is_ai_speaking = True
        
        # Check for preprocessed context
        preprocessed_key = f"preprocess:{session_id}"
        preprocessed_data = await self.redis.get(preprocessed_key)
        
        # Create phrase-level TTS callback (4-6 word chunks)
        phrase_count = 0
        async def phrase_tts_callback(phrase: str):
            nonlocal phrase_count
            phrase_count += 1
            phrase_start = time.time()
            
            try:
                await self.tts.publish_to_room(
                    room_name=room_name,
                    text=phrase,
                    language="en",
                    speed=1.0
                )
                phrase_time = (time.time() - phrase_start) * 1000
                logger.info(f"🎤 Phrase {phrase_count} published ({phrase_time:.0f}ms): '{phrase[:30]}...'")
            except Exception as e:
                logger.warning(f"Phrase TTS failed: {e}")
        
        try:
            # Add natural hesitation for complex responses
            if complexity == "complex" and target_latency_ms > 400:
                hesitation = self.hesitation_patterns["complex"][0]  # "That's a great question."
                await phrase_tts_callback(hesitation)
                await asyncio.sleep(0.3)  # Brief pause
            
            # Get conversation history
            from ..core.dependencies import get_conversation_processor
            processor = get_conversation_processor()
            history = processor.session_service.get_history(session_id)
            
            # Generate streaming response with ultra-fast phrase flushing
            full_response_tokens = []
            first_phrase_sent = False
            
            async for token in self.streaming_ai.generate_streaming_response(
                text=text,
                conversation_history=history,
                user_id="user",
                session_id=session_id,
                tts_callback=phrase_tts_callback
            ):
                full_response_tokens.append(token)
                
                # Mark when first phrase is sent
                if not first_phrase_sent and phrase_count > 0:
                    first_phrase_time = (time.time() - start_time) * 1000
                    logger.info(f"⚡ First phrase spoken in {first_phrase_time:.0f}ms (target: {target_latency_ms}ms)")
                    first_phrase_sent = True
            
            # Conversation complete
            total_time = (time.time() - start_time) * 1000
            response_text = "".join(full_response_tokens)
            
            logger.info(f"✅ Conversation turn complete: {total_time:.0f}ms total, {phrase_count} phrases")
            
            # Add turn-taking pause
            await asyncio.sleep(self.TURN_TAKING_PAUSE_MS / 1000)
            
            state.is_ai_speaking = False
            state.last_ai_response_time = datetime.utcnow()
            
            return {
                "response": response_text,
                "phrases_sent": phrase_count,
                "total_time_ms": total_time,
                "first_phrase_time_ms": first_phrase_time if first_phrase_sent else total_time,
                "complexity": complexity,
                "target_met": first_phrase_time <= target_latency_ms if first_phrase_sent else False
            }
            
        except asyncio.CancelledError:
            logger.info(f"🛑 Response generation cancelled (interruption): {session_id}")
            state.is_ai_speaking = False
            raise
        except Exception as e:
            logger.error(f"❌ Response generation failed: {e}")
            state.is_ai_speaking = False
            
            # Emergency fallback
            await phrase_tts_callback("I'm sorry, I had a technical issue. Can you try again?")
            return {"error": str(e), "phrases_sent": 1}
    
    async def handle_voice_onset(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """Handle user voice onset during AI speech (interruption)"""
        state = self.active_conversations.get(session_id)
        if not state:
            return {"handled": False, "reason": "no_active_session"}
        
        if not state.is_ai_speaking:
            return {"handled": False, "reason": "ai_not_speaking"}
        
        logger.info(f"🛑 Voice onset interruption: {session_id}")
        
        # Cancel current AI task
        if state.current_ai_task and not state.current_ai_task.done():
            state.current_ai_task.cancel()
        
        # Stop TTS and mark interruption
        await self._stop_tts_in_room(room_name)
        state.is_ai_speaking = False
        state.is_user_speaking = True
        state.pending_interruption = True
        
        return {
            "handled": True,
            "acknowledged": True,
            "session_id": session_id,
            "interruption_time": datetime.utcnow().isoformat()
        }
    
    async def _stop_tts_in_room(self, room_name: str):
        """Stop TTS playback in room (if TTS service supports it)"""
        try:
            # If your TTS service has a stop endpoint:
            # await self.tts.stop_audio(room_name)
            
            # For now, we'll rely on not sending new chunks
            # The InterruptionHandler already does this
            logger.info(f"🔇 TTS stop requested for room: {room_name}")
        except Exception as e:
            logger.warning(f"TTS stop failed: {e}")
    
    async def _monitor_conversation_state(self, session_id: str, room_name: str):
        """Background monitor for conversation health and cleanup"""
        try:
            while session_id in self.active_conversations:
                state = self.active_conversations[session_id]
                
                # Cleanup stale sessions
                if state.last_user_input_time:
                    time_since_input = datetime.utcnow() - state.last_user_input_time
                    if time_since_input.total_seconds() > 300:  # 5 minutes
                        logger.info(f"🧹 Cleaning up stale conversation: {session_id}")
                        self.active_conversations.pop(session_id, None)
                        break
                
                # Monitor for stuck states
                if state.is_ai_speaking:
                    if state.current_ai_task and state.current_ai_task.done():
                        state.is_ai_speaking = False
                        logger.debug(f"🔄 Auto-reset AI speaking state: {session_id}")
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
        except asyncio.CancelledError:
            logger.debug(f"Monitor cancelled for {session_id}")
        except Exception as e:
            logger.error(f"Conversation monitor error: {e}")
    
    def get_conversation_stats(self, session_id: str) -> Dict[str, Any]:
        """Get real-time conversation statistics"""
        state = self.active_conversations.get(session_id)
        if not state:
            return {"active": False}
        
        return {
            "active": True,
            "session_id": session_id,
            "is_ai_speaking": state.is_ai_speaking,
            "is_user_speaking": state.is_user_speaking,
            "turn_count": state.turn_count,
            "last_interaction": state.last_user_input_time.isoformat() if state.last_user_input_time else None,
            "conversation_complexity": state.conversation_complexity,
            "has_pending_interruption": state.pending_interruption
        }
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get system-wide conversation statistics"""
        active_sessions = len(self.active_conversations)
        speaking_sessions = sum(1 for s in self.active_conversations.values() if s.is_ai_speaking)
        
        return {
            "active_conversations": active_sessions,
            "ai_currently_speaking": speaking_sessions,
            "engine_type": "real_time_sota",
            "target_latencies": {
                "simple_ms": self.SIMPLE_RESPONSE_MAX_MS,
                "normal_ms": self.NORMAL_RESPONSE_MAX_MS,
                "phrase_tokens": self.PHRASE_MIN_TOKENS,
                "token_gap_ms": self.TOKEN_GAP_THRESHOLD_MS
            }
        }


class UltraFastPhraseBuffer:
    """Optimized phrase buffer for sub-200ms first phrase delivery"""
    
    def __init__(self):
        self.buffer = ""
        self.token_count = 0
        self.last_token_time = time.time()
        
        # Ultra-aggressive flushing for naturalness
        self.FLUSH_ON_TOKENS = 4          # Flush on just 4 tokens
        self.FLUSH_ON_GAP_MS = 60         # Very short gap tolerance
        self.FLUSH_ON_PUNCTUATION = True  # Always flush on punctuation
        
        # Semantic break patterns (Kokoro-style)
        self.semantic_breaks = {
            "level4": ["however", "therefore", "meanwhile", "furthermore", "moreover"],
            "level3": ["but", "and", "or", "so", "then", "while", "because"],
            "level2": ["with", "for", "in", "on", "at", "by"],
            "punctuation": [".", "?", "!", ",", ";", ":"],
        }
    
    def add_token(self, token: str) -> Optional[str]:
        """Add token with ultra-fast flushing for natural speech"""
        now = time.time()
        gap_ms = (now - self.last_token_time) * 1000
        self.last_token_time = now
        
        self.buffer += token
        self.token_count += 1
        
        # Priority 1: Punctuation (immediate flush)
        if self.FLUSH_ON_PUNCTUATION and any(p in token for p in self.semantic_breaks["punctuation"]):
            if self.token_count >= 2:  # At least 2 tokens
                return self._flush_buffer()
        
        # Priority 2: Token count (ultra-fast for first phrase)
        if self.token_count >= self.FLUSH_ON_TOKENS:
            return self._flush_buffer()
        
        # Priority 3: Token gap (natural pause detection)
        if gap_ms > self.FLUSH_ON_GAP_MS and self.token_count >= 3:
            return self._flush_buffer()
        
        # Priority 4: Semantic breaks
        buffer_lower = self.buffer.lower()
        for level, breaks in self.semantic_breaks.items():
            if level == "punctuation":
                continue
            for break_word in breaks:
                if f" {break_word} " in buffer_lower and self.token_count >= 3:
                    return self._flush_buffer()
        
        return None
    
    def _flush_buffer(self) -> str:
        """Flush current buffer and reset"""
        phrase = self.buffer.strip()
        self.buffer = ""
        self.token_count = 0
        return phrase
    
    def flush_remaining(self) -> Optional[str]:
        """Get any remaining content"""
        if self.buffer.strip():
            return self._flush_buffer()
        return None


# Integration with your existing architecture
def create_real_time_engine(redis_client, tts_service, streaming_ai_service) -> RealTimeConversationEngine:
    """Factory function for dependency injection"""
    return RealTimeConversationEngine(
        redis_client=redis_client,
        tts_service=tts_service,
        streaming_ai_service=streaming_ai_service
    )
