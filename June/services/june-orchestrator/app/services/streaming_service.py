#!/usr/bin/env python3
"""
Streaming AI Service - SOTA Ultra-Fast Implementation
Optimized for 2-token emergency first phrases and 60ms sensitivity
"""
import logging
import time
import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any, List, Callable
from dataclasses import dataclass

from ..config import config
from ..security.cost_tracker import circuit_breaker
from .tts_service import tts_service

logger = logging.getLogger("streaming-ai")

# SOTA tuning - ultra-aggressive for naturalness
PHRASE_MIN_TOKENS = int(os.getenv("PHRASE_MIN_TOKENS", "4"))
TOKEN_GAP_MS = int(os.getenv("TOKEN_GAP_MS", "60"))
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "100"))           # Smaller
FIRST_PHRASE_URGENCY_TOKENS = int(os.getenv("FIRST_PHRASE_TOKENS", "2"))  # Emergency: 2 tokens
STREAMING_ENABLED = os.getenv("AI_STREAMING_ENABLED", "true").lower() == "true"
CONCURRENT_TTS_ENABLED = os.getenv("CONCURRENT_TTS_ENABLED", "true").lower() == "true"

@dataclass
class StreamingMetrics:
    first_token_times: List[float]
    first_phrase_times: List[float]
    phrase_counts: List[int]
    concurrent_tts_count: int
    streaming_requests: int
    ultra_fast_triggers: int

    def __post_init__(self):
        for attr in ['first_token_times', 'first_phrase_times', 'phrase_counts']:
            if not hasattr(self, attr) or getattr(self, attr) is None:
                setattr(self, attr, [])
        for attr in ['concurrent_tts_count', 'streaming_requests', 'ultra_fast_triggers']:
            if not hasattr(self, attr) or getattr(self, attr) is None:
                setattr(self, attr, 0)

    def record_first_token(self, ms: float): self.first_token_times.append(ms)
    def record_first_phrase(self, ms: float): 
        self.first_phrase_times.append(ms)
        if ms <= 200: self.ultra_fast_triggers += 1
    def record_phrase_count(self, count: int): self.phrase_counts.append(count)
    def record_concurrent_tts(self): self.concurrent_tts_count += 1
    def record_streaming_request(self): self.streaming_requests += 1

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "avg_first_token_ms": 0,
            "avg_first_phrase_ms": 0,
            "avg_phrases_per_response": 0,
            "ultra_fast_triggers": self.ultra_fast_triggers,
            "concurrent_tts_triggers": self.concurrent_tts_count,
            "streaming_requests": self.streaming_requests,
            "naturalness_score": 0
        }
        
        if self.first_token_times:
            stats["avg_first_token_ms"] = round(sum(self.first_token_times)/len(self.first_token_times), 1)
        if self.first_phrase_times:
            avg_phrase = sum(self.first_phrase_times)/len(self.first_phrase_times)
            stats["avg_first_phrase_ms"] = round(avg_phrase, 1)
            stats["naturalness_score"] = round(min(100, max(0, 100 - avg_phrase/10)), 1)
        if self.phrase_counts:
            stats["avg_phrases_per_response"] = round(sum(self.phrase_counts)/len(self.phrase_counts), 1)
        
        return stats

class UltraFastPhraseBuffer:
    """Emergency phrase buffer - gets SOMETHING out in <400ms"""
    
    def __init__(self):
        self.buffer = ""
        self.token_count = 0
        self.last_token_time = time.time()
        self.phrase_count = 0
        self.first_phrase_sent = False
        
        self.punctuation = [".", "?", "!", ",", ";", ":"]
        self.semantic_breaks = ["but", "and", "or", "so", "then", "however", "because", "while"]
    
    def add_token(self, token: str) -> Optional[str]:
        """Ultra-aggressive token flushing"""
        now = time.time()
        gap_ms = (now - self.last_token_time) * 1000
        self.last_token_time = now
        
        self.buffer += token
        self.token_count += 1
        
        # EMERGENCY: Get first phrase out ASAP (2 tokens minimum)
        if not self.first_phrase_sent and self.token_count >= FIRST_PHRASE_URGENCY_TOKENS:
            words = self.buffer.split()
            if len(words) >= 2:  # "Hello there" or "I think"
                phrase = self._flush_buffer()
                self.first_phrase_sent = True
                logger.debug(f"⚡ EMERGENCY first phrase ({self.token_count} tokens): '{phrase[:20]}...'")
                return phrase
        
        # PUNCTUATION: Always flush
        if any(p in token for p in self.punctuation):
            return self._flush_buffer()
        
        # SEMANTIC BREAKS: Natural conversation flow
        buffer_lower = self.buffer.lower()
        for break_word in self.semantic_breaks:
            if f" {break_word} " in buffer_lower and self.token_count >= 3:
                return self._flush_buffer()
        
        # TOKEN COUNT: Standard phrase completion
        if self.token_count >= PHRASE_MIN_TOKENS:
            return self._flush_buffer()
        
        # TOKEN GAP: Natural pause
        if gap_ms > TOKEN_GAP_MS and self.token_count >= 2:
            return self._flush_buffer()
        
        # LENGTH OVERFLOW: Prevent huge chunks
        if len(self.buffer) >= MAX_CHUNK_CHARS:
            return self._flush_buffer()
        
        return None
    
    def _flush_buffer(self) -> str:
        phrase = self.buffer.strip()
        self.buffer = ""
        self.token_count = 0
        self.phrase_count += 1
        return phrase
    
    def flush_remaining(self) -> Optional[str]:
        if self.buffer.strip():
            return self._flush_buffer()
        return None
    
    def get_phrase_count(self) -> int:
        return self.phrase_count
    
    def reset(self):
        self.buffer = ""
        self.token_count = 0
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.last_token_time = time.time()

class StreamingAIService:
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
        """Ultra-fast streaming with 2-token emergency phrases"""
        
        if not STREAMING_ENABLED:
            from .ai_service import generate_response
            response, _ = await generate_response(text, user_id, session_id, conversation_history)
            yield response
            return
        
        start_time = time.time()
        first_token_recorded = False
        first_phrase_recorded = False
        
        phrase_buffer = UltraFastPhraseBuffer()
        self.metrics.record_streaming_request()
        
        try:
            can_call, reason = circuit_breaker.should_allow_call()
            if not can_call:
                logger.error(f"🚨 Circuit breaker: {reason}")
                yield "I'm temporarily unavailable. Please try again."
                return
            
            from .ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, conversation_history, user_id)
            
            if hasattr(config, 'services') and getattr(config.services, 'gemini_api_key', None):
                async for token in self._stream_gemini_ultra_fast(prompt):
                    if not first_token_recorded:
                        first_token_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_token(first_token_time)
                        logger.info(f"⚡ SOTA First token: {first_token_time:.0f}ms")
                        first_token_recorded = True
                    
                    yield token
                    
                    if CONCURRENT_TTS_ENABLED and tts_callback:
                        phrase = phrase_buffer.add_token(token)
                        if phrase:
                            if not first_phrase_recorded:
                                first_phrase_time = (time.time() - start_time) * 1000
                                self.metrics.record_first_phrase(first_phrase_time)
                                logger.info(f"🎤 SOTA First phrase: {first_phrase_time:.0f}ms - '{phrase[:30]}...'")
                                first_phrase_recorded = True
                            
                            self.metrics.record_concurrent_tts()
                            asyncio.create_task(self._safe_tts_publish(tts_callback, phrase, session_id))
                
                # Final phrase
                remaining = phrase_buffer.flush_remaining()
                if remaining and CONCURRENT_TTS_ENABLED and tts_callback:
                    logger.info(f"🎤 SOTA Final phrase: '{remaining[:30]}...'")
                    asyncio.create_task(self._safe_tts_publish(tts_callback, remaining, session_id))
                
                total_phrases = phrase_buffer.get_phrase_count()
                self.metrics.record_phrase_count(total_phrases)
                
                total_time = (time.time() - start_time) * 1000
                logger.info(f"✅ SOTA Streaming complete: {total_time:.0f}ms total, {total_phrases} phrases")
                
            else:
                logger.warning("⚠️ No Gemini API, fallback")
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
                
        except asyncio.CancelledError:
            logger.info(f"🛑 Streaming cancelled: {session_id}")
            raise
        except Exception as e:
            logger.error(f"❌ SOTA error: {e}")
            try:
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
            except Exception as ee:
                logger.error(f"❌ Fallback failed: {ee}")
                yield "I'm experiencing technical difficulties. Please try again."
    
    async def _stream_gemini_ultra_fast(self, prompt: str) -> AsyncIterator[str]:
        """Gemini optimized for minimal first token latency"""
        try:
            from google import genai
            
            client = genai.Client(api_key=config.services.gemini_api_key)
            
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=160,     # Shorter for speed
                    top_p=0.85,
                    top_k=25,                 # Smaller search space
                ),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"❌ Ultra-fast Gemini error: {e}")
            try:
                from google import genai
                client = genai.Client(api_key=config.services.gemini_api_key)
                for chunk in client.models.generate_content_stream(
                    model='gemini-2.0-flash',
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(temperature=0.7, max_output_tokens=180),
                ):
                    if chunk.text:
                        yield chunk.text
            except Exception as ee:
                logger.error(f"❌ Gemini fallback failed: {ee}")
                raise
    
    async def _safe_tts_publish(self, tts_callback: Callable, phrase: str, session_id: str):
        try:
            await tts_callback(phrase)
        except Exception as e:
            logger.warning(f"TTS publish failed for {session_id}: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        return self.metrics.get_stats()

# Global instance
streaming_ai_service = StreamingAIService()

# Legacy compatibility
class LegacyStreamingMetrics:
    def __init__(self):
        self.partial_count = 0
        self.final_count = 0
        self.first_partial_times = []
    
    def record_partial(self, ms: float):
        self.partial_count += 1
        if self.partial_count == 1:
            self.first_partial_times.append(ms)
    
    def record_final(self):
        self.final_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        avg_first = sum(self.first_partial_times)/len(self.first_partial_times) if self.first_partial_times else 0
        return {
            "partial_transcripts": self.partial_count,
            "final_transcripts": self.final_count,
            "avg_first_partial_ms": round(avg_first, 1),
            "streaming_mode": "ULTRA_SOTA_OPTIMIZED"
        }

streaming_metrics = LegacyStreamingMetrics()
