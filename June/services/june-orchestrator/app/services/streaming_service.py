#!/usr/bin/env python3
"""
Streaming AI Service - FULL ONLINE PIPELINE
Concurrent processing for voice AI with online LLM processing
Implements streaming LLM + sentence segmentation + concurrent TTS triggering

FULL ONLINE PIPELINE FEATURES:
- Starts LLM processing immediately on first partial transcript
- Maintains rolling context buffer from continuous partials
- Streams LLM tokens as they are generated
- Triggers TTS on sentence boundaries for natural flow
- Achieves true speech-in + thinking + speech-out overlap

FIXED: Correct Gemini 2.0 Flash streaming API implementation
ENHANCED: Online processing with partial context updates
"""
import logging
import time
import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any, List
from dataclasses import dataclass
from collections import deque
from datetime import datetime

from ..config import config
from ..security.cost_tracker import circuit_breaker

logger = logging.getLogger("streaming-ai")

# Feature flags (robust)
def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED = getattr(config, "AI_STREAMING_ENABLED", _bool_env("AI_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
ONLINE_PROCESSING_ENABLED = _bool_env("ONLINE_LLM_ENABLED", True)  # NEW: Enable online processing


@dataclass
class StreamingMetrics:
    """Track streaming AI performance with online processing metrics"""
    first_token_times: List[float]
    sentence_completion_times: List[float] 
    concurrent_tts_count: int
    streaming_requests: int
    online_sessions: int  # NEW: Track online sessions
    partial_contexts: int  # NEW: Track partial context updates
    
    def __post_init__(self):
        if not hasattr(self, 'first_token_times'):
            self.first_token_times = []
        if not hasattr(self, 'sentence_completion_times'):
            self.sentence_completion_times = []
        if not hasattr(self, 'concurrent_tts_count'):
            self.concurrent_tts_count = 0
        if not hasattr(self, 'streaming_requests'):
            self.streaming_requests = 0
        if not hasattr(self, 'online_sessions'):
            self.online_sessions = 0
        if not hasattr(self, 'partial_contexts'):
            self.partial_contexts = 0
            
    def record_first_token(self, time_ms: float):
        self.first_token_times.append(time_ms)
        
    def record_sentence_complete(self, time_ms: float):
        self.sentence_completion_times.append(time_ms)
        
    def record_concurrent_tts(self):
        self.concurrent_tts_count += 1
        
    def record_streaming_request(self):
        self.streaming_requests += 1
        
    def record_online_session(self):
        """NEW: Record online session start"""
        self.online_sessions += 1
        
    def record_partial_context(self):
        """NEW: Record partial context update"""
        self.partial_contexts += 1
        
    def get_stats(self) -> Dict[str, Any]:
        avg_first_token = sum(self.first_token_times) / len(self.first_token_times) if self.first_token_times else 0
        avg_sentence_time = sum(self.sentence_completion_times) / len(self.sentence_completion_times) if self.sentence_completion_times else 0
        
        return {
            "avg_first_token_ms": round(avg_first_token, 1),
            "avg_sentence_completion_ms": round(avg_sentence_time, 1),
            "concurrent_tts_triggers": self.concurrent_tts_count,
            "streaming_requests": self.streaming_requests,
            "online_sessions_started": self.online_sessions,
            "partial_context_updates": self.partial_contexts,
            "total_tokens_processed": len(self.first_token_times),
            "pipeline_mode": "ONLINE" if ONLINE_PROCESSING_ENABLED else "STREAMING"
        }


class OnlineContextBuffer:
    """NEW: Manages rolling context from partial transcripts for online LLM"""
    
    def __init__(self, max_partials: int = 10):
        self.partials = deque(maxlen=max_partials)
        self.last_update = datetime.utcnow()
        self.context_version = 0
        
    def add_partial(self, text: str, sequence: int) -> bool:
        """Add partial and return if context significantly changed"""
        # Only add if it's meaningfully different
        if not self.partials or len(text) > len(self.partials[-1]) + 3:
            self.partials.append(text)
            self.last_update = datetime.utcnow()
            self.context_version += 1
            return True
        return False
        
    def get_current_context(self) -> str:
        """Get best current context for LLM"""
        return self.partials[-1] if self.partials else ""
        
    def get_context_progression(self) -> List[str]:
        """Get progression of partial contexts"""
        return list(self.partials)
        
    def is_stale(self, max_age_seconds: int = 15) -> bool:
        """Check if context is too old"""
        age = (datetime.utcnow() - self.last_update).total_seconds()
        return age > max_age_seconds
        
    def reset(self):
        """Reset for new utterance"""
        self.partials.clear()
        self.context_version = 0
        self.last_update = datetime.utcnow()


class SentenceBuffer:
    """Smart sentence completion detection for streaming TTS triggers"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}  # Multi-language
        self.sentence_starters = {'the', 'a', 'an', 'i', 'you', 'we', 'they', 'it', 'he', 'she'}
        self.min_sentence_length = 8  # OPTIMIZED: Shorter minimum for faster TTS
        
    def add_token(self, token: str) -> Optional[str]:
        """Add token and return complete sentence if ready for TTS"""
        self.buffer += token
        
        # Check for sentence completion
        if any(ending in token for ending in self.sentence_endings):
            sentence = self.buffer.strip()
            
            # Validate sentence quality for TTS
            if (len(sentence) >= self.min_sentence_length and 
                self._is_complete_sentence(sentence)):
                
                self.buffer = ""
                return sentence
                
        # Handle long buffers (send reasonable chunks for TTS)
        if len(self.buffer) > 150:  # OPTIMIZED: Smaller chunks for streaming
            # Find reasonable break point
            break_points = [',', ';', ' and ', ' or ', ' but ', ' so ', ' then ']
            for bp in break_points:
                if bp in self.buffer[-80:]:
                    idx = self.buffer.rfind(bp)
                    sentence = self.buffer[:idx + len(bp)].strip()
                    self.buffer = self.buffer[idx + len(bp):].strip()
                    if len(sentence) >= self.min_sentence_length:
                        return sentence
                    break
                    
        return None
        
    def _is_complete_sentence(self, sentence: str) -> bool:
        """Enhanced sentence completeness heuristics"""
        sentence_lower = sentence.lower().strip()
        
        # Skip very short fragments
        if len(sentence_lower) < self.min_sentence_length:
            return False
            
        # Skip common incomplete patterns
        incomplete_patterns = ['um.', 'uh.', 'er.', 'ah.', 'well.', 'so.', 'and.']
        if any(sentence_lower.endswith(p) for p in incomplete_patterns):
            return False
            
        # Check for reasonable word count
        word_count = len(sentence.split())
        if word_count < 2:
            return False
            
        return True
        
    def flush_remaining(self) -> Optional[str]:
        """Get remaining buffer as final sentence"""
        if len(self.buffer.strip()) >= self.min_sentence_length:
            sentence = self.buffer.strip()
            self.buffer = ""
            return sentence
        return None
        
    def reset(self):
        """Reset buffer state"""
        self.buffer = ""


class StreamingAIService:
    """ENHANCED: Streaming AI service with online partial processing"""
    
    def __init__(self):
        self.metrics = StreamingMetrics([], [], 0, 0, 0, 0)
        
    async def generate_streaming_response(
        self,
        text: str,
        conversation_history: List[Dict],
        user_id: str,
        session_id: str,
        tts_callback=None
    ) -> AsyncIterator[str]:
        """Generate streaming AI response with concurrent TTS triggering"""
        
        if not STREAMING_ENABLED:
            # Fallback to non-streaming
            from .ai_service import generate_response
            response, _ = await generate_response(text, user_id, session_id, conversation_history)
            yield response
            return
            
        start_time = time.time()
        first_token = True
        sentence_buffer = SentenceBuffer()
        
        self.metrics.record_streaming_request()
        
        try:
            # Check circuit breaker
            can_call, reason = circuit_breaker.should_allow_call()
            if not can_call:
                logger.error(f"🚨 Streaming AI blocked by circuit breaker: {reason}")
                yield "I'm temporarily unavailable. Please try again in a moment."
                return
                
            # Build context (reuse from ai_service)
            from .ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, conversation_history, user_id)
            
            # Try Gemini streaming if available
            if hasattr(config, 'services') and hasattr(config.services, 'gemini_api_key') and config.services.gemini_api_key:
                async for token in self._stream_gemini(prompt):
                    # Record first token latency
                    if first_token:
                        first_token_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_token(first_token_time)
                        logger.info(f"⚡ First token in {first_token_time:.0f}ms")
                        first_token = False
                        
                    yield token
                    
                    # Check for sentence completion and trigger TTS
                    if CONCURRENT_TTS_ENABLED and tts_callback:
                        sentence = sentence_buffer.add_token(token)
                        if sentence:
                            sentence_time = (time.time() - start_time) * 1000
                            self.metrics.record_sentence_complete(sentence_time)
                            self.metrics.record_concurrent_tts()
                            
                            logger.info(f"🎤 Concurrent TTS trigger ({sentence_time:.0f}ms): {sentence[:50]}...")
                            
                            # Trigger TTS in background (non-blocking)
                            asyncio.create_task(tts_callback(sentence))
                            
                # Handle any remaining buffer
                remaining = sentence_buffer.flush_remaining()
                if remaining and CONCURRENT_TTS_ENABLED and tts_callback:
                    logger.info(f"🎤 Final TTS trigger: {remaining[:50]}...")
                    asyncio.create_task(tts_callback(remaining))
                    
            else:
                # Fallback to non-streaming
                logger.warning("⚠️ Gemini API not configured, using fallback")
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
                
        except Exception as e:
            logger.error(f"❌ Streaming AI error: {e}")
            # Fallback to regular AI service
            try:
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
            except Exception as fallback_error:
                logger.error(f"❌ Fallback AI also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties. Please try again."
    
    async def generate_online_streaming_response(
        self,
        partial_context: str,
        conversation_history: List[Dict],
        user_id: str,
        session_id: str,
        tts_callback=None,
        context_buffer: Optional['OnlineContextBuffer'] = None
    ) -> AsyncIterator[str]:
        """NEW: Generate streaming response for online processing with rolling partial context"""
        
        if not ONLINE_PROCESSING_ENABLED or not STREAMING_ENABLED:
            # Fallback to regular streaming
            async for token in self.generate_streaming_response(
                partial_context, conversation_history, user_id, session_id, tts_callback
            ):
                yield token
            return
            
        start_time = time.time()
        first_token = True
        sentence_buffer = SentenceBuffer()
        
        self.metrics.record_streaming_request()
        self.metrics.record_online_session()
        
        logger.info(f"🧠 Starting ONLINE LLM with partial context: '{partial_context[:30]}...'")
        
        try:
            # Check circuit breaker
            can_call, reason = circuit_breaker.should_allow_call()
            if not can_call:
                logger.error(f"🚨 Online LLM blocked by circuit breaker: {reason}")
                yield "I'm temporarily unavailable. Please try again in a moment."
                return
                
            # Build context for online processing
            from .ai_service import build_context_for_voice
            
            # Use partial context as the "user input" for now
            # The context may update as more partials arrive
            prompt = build_context_for_voice(partial_context, conversation_history, user_id)
            
            # Try Gemini streaming with online processing
            if hasattr(config, 'services') and hasattr(config.services, 'gemini_api_key') and config.services.gemini_api_key:
                token_count = 0
                async for token in self._stream_gemini_online(prompt, context_buffer):
                    token_count += 1
                    
                    # Record first token latency (this is the key metric for online processing)
                    if first_token:
                        first_token_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_token(first_token_time)
                        logger.info(f"⚡ ONLINE First token in {first_token_time:.0f}ms (from first partial)")
                        first_token = False
                        
                    yield token
                    
                    # Check for sentence completion and trigger TTS immediately
                    if CONCURRENT_TTS_ENABLED and tts_callback:
                        sentence = sentence_buffer.add_token(token)
                        if sentence:
                            sentence_time = (time.time() - start_time) * 1000
                            self.metrics.record_sentence_complete(sentence_time)
                            self.metrics.record_concurrent_tts()
                            
                            logger.info(f"🎤 ONLINE TTS trigger ({sentence_time:.0f}ms): {sentence[:50]}...")
                            
                            # Trigger TTS immediately (non-blocking)
                            asyncio.create_task(tts_callback(sentence))
                
                logger.info(f"✅ Online LLM completed: {token_count} tokens")
                            
                # Handle any remaining buffer
                remaining = sentence_buffer.flush_remaining()
                if remaining and CONCURRENT_TTS_ENABLED and tts_callback:
                    logger.info(f"🎤 ONLINE Final TTS: {remaining[:50]}...")
                    asyncio.create_task(tts_callback(remaining))
                    
            else:
                # Fallback to non-streaming
                logger.warning("⚠️ Gemini API not configured for online processing, using fallback")
                from .ai_service import generate_response
                response, _ = await generate_response(partial_context, user_id, session_id, conversation_history)
                yield response
                
        except asyncio.CancelledError:
            logger.info(f"🛑 Online LLM processing cancelled for {user_id}")
            raise
        except Exception as e:
            logger.error(f"❌ Online LLM error: {e}")
            # Fallback to regular processing
            try:
                from .ai_service import generate_response
                response, _ = await generate_response(partial_context, user_id, session_id, conversation_history)
                yield response
            except Exception as fallback_error:
                logger.error(f"❌ Online fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties. Please try again."
            
    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        """Stream tokens from Gemini API - FIXED IMPLEMENTATION"""
        try:
            from google import genai
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            # FIXED: Use the correct streaming API method
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200,
                )
            ):
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini streaming error: {e}")
            # Fallback to single response
            from .ai_service import generate_response
            try:
                response, _ = await generate_response(
                    prompt.split("User:")[-1].strip() if "User:" in prompt else prompt,
                    "streaming-fallback", "streaming-session", []
                )
                yield response
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties. Please try again."
    
    async def _stream_gemini_online(self, prompt: str, context_buffer: Optional['OnlineContextBuffer'] = None) -> AsyncIterator[str]:
        """NEW: Stream from Gemini with online context updates"""
        try:
            from google import genai
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            # Enhanced prompt for online processing
            online_prompt = prompt
            if context_buffer:
                progression = context_buffer.get_context_progression()
                if len(progression) > 1:
                    online_prompt += f"\n\n[Context progression: {' → '.join(progression[-3:])}]"
            
            # OPTIMIZED: Faster generation for online processing
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash',
                contents=online_prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.6,  # Slightly lower for consistency
                    max_output_tokens=150,  # OPTIMIZED: Shorter for online processing
                    top_p=0.9,
                    top_k=40,
                )
            ):
                if chunk.text:
                    yield chunk.text
                    
                    # Update context buffer with current response if available
                    if context_buffer:
                        self.metrics.record_partial_context()
                    
        except Exception as e:
            logger.error(f"❌ Online Gemini streaming error: {e}")
            # Try regular streaming as fallback
            async for token in self._stream_gemini(prompt):
                yield token
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get streaming performance metrics"""
        return self.metrics.get_stats()


# Performance metrics for streaming
class LegacyStreamingMetrics:
    """Legacy metrics class for compatibility"""
    def __init__(self):
        self.partial_count = 0
        self.final_count = 0
        self.first_partial_times = []
        self.partial_intervals = []
        self.last_partial_time = None
        
    def record_partial(self, processing_time_ms: float):
        """Record partial transcript metrics"""
        now = time.time()
        self.partial_count += 1
        
        if self.partial_count == 1:
            self.first_partial_times.append(processing_time_ms)
            
        if self.last_partial_time:
            interval = (now - self.last_partial_time) * 1000
            self.partial_intervals.append(interval)
            
        self.last_partial_time = now
        
    def record_final(self):
        """Record final transcript completion"""
        self.final_count += 1
        self.last_partial_time = None
        
    def get_stats(self) -> Dict[str, Any]:
        """Get streaming performance statistics"""
        avg_first_partial = sum(self.first_partial_times) / len(self.first_partial_times) if self.first_partial_times else 0
        avg_interval = sum(self.partial_intervals) / len(self.partial_intervals) if self.partial_intervals else 0
        
        return {
            "partial_transcripts": self.partial_count,
            "final_transcripts": self.final_count,
            "avg_first_partial_ms": round(avg_first_partial, 1),
            "avg_partial_interval_ms": round(avg_interval, 1),
            "streaming_efficiency": round(self.partial_count / max(1, self.final_count), 2),
            "online_processing": ONLINE_PROCESSING_ENABLED
        }


# Global streaming service instance
streaming_ai_service = StreamingAIService()

# Legacy compatibility
streaming_metrics = LegacyStreamingMetrics()