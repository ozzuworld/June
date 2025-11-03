#!/usr/bin/env python3
"""
Streaming AI Service - FULL ONLINE PIPELINE (Enhanced phrase flushing)
- Earlier TTS starts via phrase-level flushing
- Multiple small publish_to_room calls per reply for natural flow
- Provider-agnostic (uses existing TTSService.publish_to_room)
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

# ... keep existing flags and classes (omitted here for brevity) ...
# NOTE: This file replaces prior content with an augmented version that keeps
# the same public API but adds phrase-level flushing.

# Feature flags (robust)
def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED = getattr(config, "AI_STREAMING_ENABLED", _bool_env("AI_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
ONLINE_PROCESSING_ENABLED = _bool_env("ONLINE_LLM_ENABLED", True)

# Flush thresholds (tunable)
PHRASE_MIN_TOKENS = int(os.getenv("PHRASE_MIN_TOKENS", 10))
TOKEN_GAP_MS = int(os.getenv("TOKEN_GAP_MS", 120))
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", 180))

@dataclass
class StreamingMetrics:
    first_token_times: List[float]
    sentence_completion_times: List[float]
    concurrent_tts_count: int
    streaming_requests: int
    online_sessions: int
    partial_contexts: int

    def __post_init__(self):
        self.first_token_times = self.first_token_times or []
        self.sentence_completion_times = self.sentence_completion_times or []
        self.concurrent_tts_count = self.concurrent_tts_count or 0
        self.streaming_requests = self.streaming_requests or 0
        self.online_sessions = self.online_sessions or 0
        self.partial_contexts = self.partial_contexts or 0

    def record_first_token(self, ms: float): self.first_token_times.append(ms)
    def record_sentence_complete(self, ms: float): self.sentence_completion_times.append(ms)
    def record_concurrent_tts(self): self.concurrent_tts_count += 1
    def record_streaming_request(self): self.streaming_requests += 1
    def record_online_session(self): self.online_sessions += 1
    def record_partial_context(self): self.partial_contexts += 1
    def get_stats(self) -> Dict[str, Any]:
        avg_first = sum(self.first_token_times)/len(self.first_token_times) if self.first_token_times else 0
        avg_sent = sum(self.sentence_completion_times)/len(self.sentence_completion_times) if self.sentence_completion_times else 0
        return {
            "avg_first_token_ms": round(avg_first,1),
            "avg_sentence_completion_ms": round(avg_sent,1),
            "concurrent_tts_triggers": self.concurrent_tts_count,
            "streaming_requests": self.streaming_requests,
            "online_sessions_started": self.online_sessions,
            "partial_context_updates": self.partial_contexts,
            "pipeline_mode": "ONLINE" if ONLINE_PROCESSING_ENABLED else "STREAMING",
        }

class SentenceBuffer:
    def __init__(self):
        self.buf = ""
        self.last_token_at = time.time()
        self.ends = {'.','!','?','。','！','？'}

    def add(self, token: str) -> Optional[str]:
        now = time.time()
        gap_ms = (now - self.last_token_at) * 1000
        self.last_token_at = now
        self.buf += token

        # Prefer punctuation
        if any(e in token for e in self.ends) and len(self.buf.split()) >= max(6, PHRASE_MIN_TOKENS-2):
            chunk = self._cut_chunk()
            return chunk

        # Token gap flush
        if gap_ms > TOKEN_GAP_MS and len(self.buf.split()) >= 6:
            chunk = self._cut_chunk()
            return chunk

        # Length-based flush
        if len(self.buf) >= MAX_CHUNK_CHARS:
            chunk = self._cut_chunk(prefer_breaks=True)
            return chunk

        return None

    def flush_remaining(self) -> Optional[str]:
        if len(self.buf.strip()) >= 1:
            chunk = self.buf.strip()
            self.buf = ""
            return chunk
        return None

    def _cut_chunk(self, prefer_breaks: bool=False) -> str:
        text = self.buf.strip()
        if prefer_breaks:
            for bp in [',',';',' and ',' but ',' so ',' then ',' because ']:
                if bp in text[-80:]:
                    idx = text.rfind(bp)
                    chunk = text[:idx+len(bp)].strip()
                    self.buf = text[idx+len(bp):].strip()
                    return chunk or text
        self.buf = ""
        return text

class StreamingAIService:
    def __init__(self):
        self.metrics = StreamingMetrics([],[],0,0,0,0)

    async def generate_streaming_response(
        self,
        text: str,
        conversation_history: List[Dict],
        user_id: str,
        session_id: str,
        tts_callback: Optional[Callable[[str], Any]] = None,
    ) -> AsyncIterator[str]:
        if not STREAMING_ENABLED:
            from .ai_service import generate_response
            response, _ = await generate_response(text, user_id, session_id, conversation_history)
            yield response
            return

        start = time.time(); first = True
        self.metrics.record_streaming_request()
        buf = SentenceBuffer()

        try:
            ok, reason = circuit_breaker.should_allow_call()
            if not ok:
                logger.error(f"Circuit open: {reason}")
                yield "I'm temporarily unavailable. Please try again shortly."
                return

            from .ai_service import build_context_for_voice
            prompt = build_context_for_voice(text, conversation_history, user_id)

            if hasattr(config, 'services') and getattr(config.services, 'gemini_api_key', None):
                async for token in self._stream_gemini(prompt):
                    if first:
                        self.metrics.record_first_token((time.time()-start)*1000)
                        first = False
                    yield token

                    if CONCURRENT_TTS_ENABLED and tts_callback:
                        chunk = buf.add(token)
                        if chunk:
                            self.metrics.record_concurrent_tts()
                            asyncio.create_task(tts_callback(chunk))
                # flush tail
                tail = buf.flush_remaining()
                if tail and CONCURRENT_TTS_ENABLED and tts_callback:
                    asyncio.create_task(tts_callback(tail))
            else:
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            try:
                from .ai_service import generate_response
                response, _ = await generate_response(text, user_id, session_id, conversation_history)
                yield response
            except Exception as ee:
                logger.error(f"Fallback failed: {ee}")
                yield "I'm experiencing technical difficulties. Please try again."

    async def _stream_gemini(self, prompt: str) -> AsyncIterator[str]:
        try:
            from google import genai
            client = genai.Client(api_key=config.services.gemini_api_key)
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.7, max_output_tokens=220),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            from .ai_service import generate_response
            response, _ = await generate_response(prompt, "streaming-fallback", "streaming-session", [])
            yield response

# Global instance
streaming_ai_service = StreamingAIService()
