#!/usr/bin/env python3
"""
Streaming AI Service - Concurrent processing for voice AI
Implements streaming LLM + sentence segmentation + concurrent TTS triggering
"""
import logging
import time
import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any, List
from dataclasses import dataclass
from collections import deque

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


@dataclass
class StreamingMetrics:
    """Track streaming AI performance"""
    first_token_times: List[float]
    sentence_completion_times: List[float] 
    concurrent_tts_count: int
    streaming_requests: int
    
    def __post_init__(self):
        if not hasattr(self, 'first_token_times'):
            self.first_token_times = []
        if not hasattr(self, 'sentence_completion_times'):
            self.sentence_completion_times = []
        if not hasattr(self, 'concurrent_tts_count'):
            self.concurrent_tts_count = 0
        if not hasattr(self, 'streaming_requests'):
            self.streaming_requests = 0
            
    def record_first_token(self, time_ms: float):
        self.first_token_times.append(time_ms)
        
    def record_sentence_complete(self, time_ms: float):
        self.sentence_completion_times.append(time_ms)
        
    def record_concurrent_tts(self):
        self.concurrent_tts_count += 1
        
    def record_streaming_request(self):
        self.streaming_requests += 1
        
    def get_stats(self) -> Dict[str, Any]:
        avg_first_token = sum(self.first_token_times) / len(self.first_token_times) if self.first_token_times else 0
        avg_sentence_time = sum(self.sentence_completion_times) / len(self.sentence_completion_times) if self.sentence_completion_times else 0
        
        return {
            "avg_first_token_ms": round(avg_first_token, 1),
            "avg_sentence_completion_ms": round(avg_sentence_time, 1),
            "concurrent_tts_triggers": self.concurrent_tts_count,
            "streaming_requests": self.streaming_requests,
            "total_tokens_processed": len(self.first_token_times)
        }


class SentenceBuffer:
    """Smart sentence completion detection for streaming"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}
        self.sentence_starters = {'the', 'a', 'an', 'i', 'you', 'we', 'they', 'it', 'he', 'she'}
        self.min_sentence_chars = 8
        
    def add_token(self, token: str) -> Optional[str]:
        """Add token and return complete sentence if ready"""
        self.buffer += token
        
        # Check for sentence completion
        if any(ending in token for ending in self.sentence_endings):
            sentence = self.buffer.strip()
            
            # Validate sentence quality
            if (len(sentence) >= self.min_sentence_chars and 
                self._is_complete_sentence(sentence)):
                
                self.buffer = ""
                return sentence
                
        # Handle long buffers (prevent infinite accumulation)
        if len(self.buffer) > 300:
            # Find reasonable break point
            break_points = [',', ';', ' and ', ' or ', ' but ', ' so ']
            for bp in break_points:
                if bp in self.buffer[-100:]:
                    idx = self.buffer.rfind(bp)
                    sentence = self.buffer[:idx + len(bp)].strip()
                    self.buffer = self.buffer[idx + len(bp):].strip()
                    if len(sentence) >= self.min_sentence_chars:
                        return sentence
                    break
                    
        return None
        
    def _is_complete_sentence(self, sentence: str) -> bool:
        """Basic sentence completeness heuristics"""
        sentence_lower = sentence.lower().strip()
        
        # Skip very short fragments
        if len(sentence_lower) < self.min_sentence_chars:
            return False
            
        # Skip common incomplete patterns
        incomplete_patterns = ['um.', 'uh.', 'er.', 'ah.', 'well.']
        if any(sentence_lower.endswith(p) for p in incomplete_patterns):
            return False
            
        return True
        
    def flush_remaining(self) -> Optional[str]:
        """Get remaining buffer as final sentence"""
        if len(self.buffer.strip()) >= self.min_sentence_chars:
            sentence = self.buffer.strip()
            self.buffer = ""
            return sentence
        return None


class StreamingAIService:
    """Streaming AI service with concurrent TTS triggering"""
    
    def __init__(self):
        self.metrics = StreamingMetrics([], [], 0, 0)
        
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
                    
                    # Check for sentence completion
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
            
    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        """Stream tokens from Gemini API"""
        try:
            from google import genai
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            # Use streaming generation
            stream = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200,
                ),
                stream=True  # Enable streaming
            )
            
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Gemini streaming error: {e}")
            # Fallback to single response
            from .ai_service import generate_response
            try:
                response, _ = await generate_response(
                    prompt.split("User:")[-1].strip(),
                    "streaming-fallback", "streaming-session", []
                )
                yield response
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties. Please try again."
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get streaming performance metrics"""
        return self.metrics.get_stats()


# Global streaming service instance
streaming_ai_service = StreamingAIService()