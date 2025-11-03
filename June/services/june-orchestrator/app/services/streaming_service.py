#!/usr/bin/env python3
"""
Streaming AI Service - ENHANCED with Ultra-Fast Phrase Delivery
Based on 2024-2025 SOTA research: 4-token chunks, 60ms gaps, immediate first phrase
"""
import logging
import time
import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any, List, Callable
from dataclasses import dataclass
from collections import deque
from datetime import datetime

from ..config import config
from ..security.cost_tracker import circuit_breaker
from .tts_service import tts_service

logger = logging.getLogger("streaming-ai")

# Feature flags
def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return v.strip().lower() in ("1", "true", "yes", "on") if v else default

STREAMING_ENABLED = _bool_env("AI_STREAMING_ENABLED", True)
CONCURRENT_TTS_ENABLED = _bool_env("CONCURRENT_TTS_ENABLED", True)

# SOTA tuning parameters (research-based)
PHRASE_MIN_TOKENS = int(os.getenv("PHRASE_MIN_TOKENS", "4"))        # Ultra-fast: 4 tokens
TOKEN_GAP_MS = int(os.getenv("TOKEN_GAP_MS", "60"))                # 60ms gap sensitivity
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "120"))         # Smaller chunks
FIRST_PHRASE_URGENCY_TOKENS = int(os.getenv("FIRST_PHRASE_TOKENS", "3"))  # Emergency first phrase

@dataclass
class StreamingMetrics:
    first_token_times: List[float]
    first_phrase_times: List[float]  # NEW: Track first phrase delivery
    phrase_counts: List[int]         # NEW: Track phrases per response
    concurrent_tts_count: int
    streaming_requests: int
    ultra_fast_triggers: int         # NEW: Track sub-200ms triggers

    def __post_init__(self):
        self.first_token_times = self.first_token_times or []
        self.first_phrase_times = self.first_phrase_times or []
        self.phrase_counts = self.phrase_counts or []
        self.concurrent_tts_count = self.concurrent_tts_count or 0
        self.streaming_requests = self.streaming_requests or 0
        self.ultra_fast_triggers = self.ultra_fast_triggers or 0

    def record_first_token(self, ms: float): self.first_token_times.append(ms)
    def record_first_phrase(self, ms: float): 
        self.first_phrase_times.append(ms)
        if ms <= 200:
            self.ultra_fast_triggers += 1
    def record_phrase_count(self, count: int): self.phrase_counts.append(count)
    def record_concurrent_tts(self): self.concurrent_tts_count += 1
    def record_streaming_request(self): self.streaming_requests += 1

    def get_stats(self) -> Dict[str, Any]:
        avg_first_token = sum(self.first_token_times)/len(self.first_token_times) if self.first_token_times else 0
        avg_first_phrase = sum(self.first_phrase_times)/len(self.first_phrase_times) if self.first_phrase_times else 0
        avg_phrases = sum(self.phrase_counts)/len(self.phrase_counts) if self.phrase_counts else 0
        
        return {
            "avg_first_token_ms": round(avg_first_token, 1),
            "avg_first_phrase_ms": round(avg_first_phrase, 1),
            "avg_phrases_per_response": round(avg_phrases, 1),
            "ultra_fast_triggers": self.ultra_fast_triggers,
            "concurrent_tts_triggers": self.concurrent_tts_count,
            "streaming_requests": self.streaming_requests,
            "naturalness_score": round(min(100, max(0, 100 - avg_first_phrase/10)), 1)  # Score based on speed
        }

class UltraFastPhraseBuffer:
    """SOTA phrase buffer optimized for immediate first phrase delivery"""
    
    def __init__(self):
        self.buffer = ""
        self.token_count = 0
        self.last_token_time = time.time()
        self.phrase_count = 0
        self.first_phrase_sent = False
        
        # Research-based semantic breaks (Kokoro + Duplex insights)
        self.level4_breaks = ["however", "therefore", "meanwhile", "furthermore", "moreover", "nonetheless"]
        self.level3_breaks = ["but", "and", "or", "so", "then", "while", "because", "since", "although"]
        self.level2_breaks = ["with", "for", "in", "on", "at", "by", "during", "after", "before"]
        self.punctuation = [".", "?", "!", ",", ";", ":"]
    
    def add_token(self, token: str) -> Optional[str]:
        """Add token with ultra-aggressive flushing for natural speech"""
        now = time.time()
        gap_ms = (now - self.last_token_time) * 1000
        self.last_token_time = now
        
        self.buffer += token
        self.token_count += 1
        
        # PRIORITY 1: Emergency first phrase (get SOMETHING out immediately)
        if not self.first_phrase_sent and self.token_count >= FIRST_PHRASE_URGENCY_TOKENS:
            # Check if we have a meaningful start
            words = self.buffer.split()
            if len(words) >= 2:  # At least 2 words for first phrase
                phrase = self._flush_buffer()
                self.first_phrase_sent = True
                return phrase
        
        # PRIORITY 2: Punctuation (always flush)
        if any(p in token for p in self.punctuation):
            return self._flush_buffer()
        
        # PRIORITY 3: Semantic breaks (natural conversation flow)
        buffer_lower = self.buffer.lower()
        
        # Level 4: Strong breaks (flush immediately)
        for break_word in self.level4_breaks:
            if f" {break_word} " in buffer_lower:
                return self._flush_buffer()
        
        # Level 3: Medium breaks (flush if enough tokens)
        if self.token_count >= 3:
            for break_word in self.level3_breaks:
                if f" {break_word} " in buffer_lower:
                    return self._flush_buffer()
        
        # PRIORITY 4: Token count (phrase completion)
        if self.token_count >= PHRASE_MIN_TOKENS:
            return self._flush_buffer()
        
        # PRIORITY 5: Token gap (natural pause)
        if gap_ms > TOKEN_GAP_MS and self.token_count >= 2:
            return self._flush_buffer()
        
        # PRIORITY 6: Length overflow (prevent huge chunks)
        if len(self.buffer) >= MAX_CHUNK_CHARS:
            return self._flush_buffer(prefer_semantic_break=True)
        
        return None
    
    def _flush_buffer(self, prefer_semantic_break: bool = False) -> str:
        """Flush buffer with optional semantic break preference"""
        text = self.buffer.strip()
        
        if prefer_semantic_break and len(text) > 60:
            # Try to find a good break point
            for break_word in self.level3_breaks + self.level2_breaks:
                if f" {break_word} " in text[-60:]:  # Look in last 60 chars
                    idx = text.rfind(f" {break_word} ")
                    chunk = text[:idx + len(break_word) + 1].strip()
                    remainder = text[idx + len(break_word) + 1:].strip()
                    if chunk and len(chunk.split()) >= 2:
                        self.buffer = remainder
                        self.token_count = len(remainder.split())
                        self.phrase_count += 1
                        return chunk
        
        # Normal flush
        self.buffer = ""
        self.token_count = 0
        self.phrase_count += 1
        return text
    
    def flush_remaining(self) -> Optional[str]:
        """Get any remaining content as final phrase"""
        if self.buffer.strip():
            return self._flush_buffer()
        return None
    
    def get_phrase_count(self) -> int:
        return self.phrase_count
    
    def reset(self):
        """Reset for new response"""
        self.buffer = ""
        self.token_count = 0
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.last_token_time = time.time()

class StreamingAIService:
    """Enhanced streaming AI with SOTA phrase delivery"""
    
    def __init__(self):
        self.metrics = StreamingMetrics([], [], [], 0, 0, 0)
    
    async def generate_streaming_response(
        self,
        text: str,
        conversation_history: List[Dict],
        user_id: str,
        session_id: str,
        tts_callback: Optional[Callable[[str], Any]] = None,
        room_name: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Generate streaming response with SOTA phrase-level TTS delivery"""
        
        if not STREAMING_ENABLED:
            from .ai_service import generate_response
            response, _ = await generate_response(text, user_id, session_id, conversation_history)
            yield response
            return
        
        start_time = time.time()
        first_token_recorded = False
        first_phrase_recorded = False
        
        # Ultra-fast phrase buffer
        phrase_buffer = UltraFastPhraseBuffer()
        
        self.metrics.record_streaming_request()
        
        try:
            # Circuit breaker check
            can_call, reason = circuit_breaker.should_allow_call()
            if not can_call:
                logger.error(f"🚨 Circuit breaker active: {reason}")
                yield "I'm temporarily unavailable. Please try again in a moment."
                return
            
            # Build AI context
            from .ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, conversation_history, user_id)
            
            # Stream with ultra-fast phrase delivery
            if hasattr(config, 'services') and getattr(config.services, 'gemini_api_key', None):
                async for token in self._stream_gemini_optimized(prompt):
                    # Record first token time
                    if not first_token_recorded:
                        first_token_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_token(first_token_time)
                        logger.info(f"⚡ SOTA First token: {first_token_time:.0f}ms")
                        first_token_recorded = True
                    
                    yield token
                    
                    # Ultra-fast phrase chunking
                    if CONCURRENT_TTS_ENABLED and tts_callback:
                        phrase = phrase_buffer.add_token(token)
                        if phrase:
                            # Record first phrase delivery time
                            if not first_phrase_recorded:
                                first_phrase_time = (time.time() - start_time) * 1000
                                self.metrics.record_first_phrase(first_phrase_time)
                                logger.info(f"🎤 SOTA First phrase: {first_phrase_time:.0f}ms - '{phrase[:30]}...'")
                                first_phrase_recorded = True
                            
                            self.metrics.record_concurrent_tts()
                            
                            # Send phrase to TTS immediately (non-blocking)
                            asyncio.create_task(self._safe_tts_publish(tts_callback, phrase, session_id))
                
                # Flush any remaining content
                remaining = phrase_buffer.flush_remaining()
                if remaining and CONCURRENT_TTS_ENABLED and tts_callback:
                    logger.info(f"🎤 SOTA Final phrase: '{remaining[:30]}...'")
                    asyncio.create_task(self._safe_tts_publish(tts_callback, remaining, session_id))
                
                # Record metrics
                total_phrases = phrase_buffer.get_phrase_count()
                self.metrics.record_phrase_count(total_phrases)
                
                total_time = (time.time() - start_time) * 1000
                logger.info(f"✅ SOTA Streaming complete: {total_time:.0f}ms total, {total_phrases} phrases")
                
            else:
                # Fallback to non-streaming
                logger.warning("⚠️ Gemini API not configured, using fallback")
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
                
        except asyncio.CancelledError:
            logger.info(f"🛑 Streaming cancelled (interruption): {session_id}")
            raise
        except Exception as e:
            logger.error(f"❌ SOTA Streaming error: {e}")
            # Fallback to regular AI service
            try:
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                yield "I'm experiencing technical difficulties. Please try again."
    
    async def _stream_gemini_optimized(self, prompt: str) -> AsyncIterator[str]:
        """Optimized Gemini streaming for minimal latency"""
        try:
            from google import genai
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            # Optimized config for speed
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',  # Use experimental for lowest latency
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.6,           # Slightly lower for consistency
                    max_output_tokens=180,     # Shorter for faster delivery
                    top_p=0.85,               # Focused sampling
                    top_k=30,                 # Reduced search space
                ),
            ):
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error(f"❌ Optimized Gemini streaming error: {e}")
            # Try regular model as fallback
            try:
                from google import genai
                client = genai.Client(api_key=config.services.gemini_api_key)
                
                for chunk in client.models.generate_content_stream(
                    model='gemini-2.0-flash',
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(temperature=0.7, max_output_tokens=200),
                ):
                    if chunk.text:
                        yield chunk.text
            except Exception as fallback_error:
                logger.error(f"❌ Gemini fallback failed: {fallback_error}")
                raise
    
    async def _safe_tts_publish(self, tts_callback: Callable, phrase: str, session_id: str):
        """Safely publish phrase to TTS with error handling"""
        try:
            await tts_callback(phrase)
        except Exception as e:
            logger.warning(f"TTS publish failed for {session_id}: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get enhanced streaming metrics"""
        return self.metrics.get_stats()

# Global streaming service instance
streaming_ai_service = StreamingAIService()

# Keep legacy compatibility
class LegacyStreamingMetrics:
    def __init__(self):
        self.partial_count = 0
        self.final_count = 0
        self.first_partial_times = []
    
    def record_partial(self, processing_time_ms: float):
        self.partial_count += 1
        if self.partial_count == 1:
            self.first_partial_times.append(processing_time_ms)
    
    def record_final(self):
        self.final_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        avg_first = sum(self.first_partial_times)/len(self.first_partial_times) if self.first_partial_times else 0
        return {
            "partial_transcripts": self.partial_count,
            "final_transcripts": self.final_count,
            "avg_first_partial_ms": round(avg_first, 1),
            "streaming_mode": "SOTA_OPTIMIZED"
        }

# Legacy instance for backward compatibility
streaming_metrics = LegacyStreamingMetrics()
