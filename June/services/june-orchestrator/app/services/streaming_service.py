import logging
import time
import asyncio
import re
from typing import Optional, AsyncIterator, Dict, Any, List, Callable
from dataclasses import dataclass
from ..config import config
from ..security.cost_tracker import circuit_breaker

logger = logging.getLogger("streaming-ai")

# Production best-practice: punctuation-based TTS sentence chunker
class UltraFastPhraseBuffer:
    """
    Buffers tokens and yields complete sentences (or well-formed long fragments)
    using strong sentence-ending punctuation, minimum chunk size, and
    fallback timeout for TTS chunking. Safe for CosyVoice2.
    """
    def __init__(self, min_length=25, timeout_ms=150):
        self.buffer = ""
        self.token_count = 0
        self.last_token_time = time.time()
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.sentence_end_re = re.compile(r'[.!?…。！？]+')
        self.min_length = min_length
        self.timeout_ms = timeout_ms
    
    def add_token(self, token: str) -> Optional[str]:
        now = time.time()
        self.buffer += token
        self.token_count += 1

        # Only yield on sentence/pause boundary AND length limit
        if self.sentence_end_re.search(self.buffer) and len(self.buffer) >= self.min_length:
            end_pos = self.sentence_end_re.search(self.buffer).end()
            phrase = self.buffer[:end_pos].strip()
            self.buffer = self.buffer[end_pos:]
            self.token_count = 0
            self.phrase_count += 1
            self.last_token_time = now
            return phrase
        # If buffer is very long and no sentence end, force yield
        elif len(self.buffer) >= self.min_length * 2:
            phrase = self.buffer.strip()
            self.buffer = ""
            self.token_count = 0
            self.phrase_count += 1
            self.last_token_time = now
            return phrase
        # Fallback: yield a long enough chunk after a long wait
        elif (now - self.last_token_time) * 1000 > self.timeout_ms and len(self.buffer) >= self.min_length:
            phrase = self.buffer.strip()
            self.buffer = ""
            self.token_count = 0
            self.phrase_count += 1
            self.last_token_time = now
            return phrase
        return None
    
    def flush_remaining(self) -> Optional[str]:
        if self.buffer.strip():
            phrase = self.buffer.strip()
            self.buffer = ""
            self.token_count = 0
            self.phrase_count += 1
            return phrase
        return None
    
    def get_phrase_count(self) -> int:
        return self.phrase_count

    def reset(self):
        self.buffer = ""
        self.token_count = 0
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.last_token_time = time.time()

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
            "naturalness_score": 0,
            "mode": "ULTRA_FAST"
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

class StreamingAIService:
    def __init__(self):
        self.metrics = StreamingMetrics([], [], [], 0, 0, 0)
    def _build_ultra_fast_prompt(self, text: str, history: List[Dict]) -> str:
        # Minimal conversational context
        system = "You are June, a helpful AI assistant. Be conversational and brief."
        recent = history[-4:] if len(history) > 4 else history
        context_parts = []
        for msg in recent:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            context_parts.append(f"{role}: {content}")
        context = "\n".join(context_parts) if context_parts else ""
        prompt = f"{system}\n\n{context}\nuser: {text}\nassistant:"
        return prompt
    async def generate_streaming_response(
        self,
        text: str,
        conversation_history: List[Dict],
        user_id: str,
        session_id: str,
        tts_callback: Optional[Callable[[str], Any]] = None,
        room_name: Optional[str] = None
    ) -> AsyncIterator[str]:
        start_time = time.time()
        first_token_recorded = False
        first_phrase_recorded = False
        phrase_buffer = UltraFastPhraseBuffer()
        self.metrics.record_streaming_request()
        try:
            can_call, reason = circuit_breaker.should_allow_call()
            if not can_call:
                logger.error(f"🚨 Circuit breaker: {reason}")
                yield "I'm temporarily unavailable."
                return
            prompt_start = time.time()
            prompt = self._build_ultra_fast_prompt(text, conversation_history)
            prompt_time = (time.time() - prompt_start) * 1000
            logger.info(f"📝 Prompt built in {prompt_time:.0f}ms")
            if hasattr(config, 'services') and getattr(config.services, 'gemini_api_key', None):
                logger.info(f"🚀 Starting Gemini stream at {(time.time() - start_time) * 1000:.0f}ms")
                async for token in self._stream_gemini_ultra_fast(prompt):
                    if not first_token_recorded:
                        first_token_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_token(first_token_time)
                        logger.info(f"⚡ First token: {first_token_time:.0f}ms")
                        first_token_recorded = True
                    yield token
                    if tts_callback:
                        phrase = phrase_buffer.add_token(token)
                        if phrase:
                            if not first_phrase_recorded:
                                first_phrase_time = (time.time() - start_time) * 1000
                                self.metrics.record_first_phrase(first_phrase_time)
                                logger.info(f"🎤 First phrase: {first_phrase_time:.0f}ms - '{phrase[:30]}...'")
                                first_phrase_recorded = True
                            self.metrics.record_concurrent_tts()
                            asyncio.create_task(self._safe_tts_publish(tts_callback, phrase, session_id))
                remaining = phrase_buffer.flush_remaining()
                if remaining and tts_callback:
                    asyncio.create_task(self._safe_tts_publish(tts_callback, remaining, session_id))
                total_phrases = phrase_buffer.get_phrase_count()
                self.metrics.record_phrase_count(total_phrases)
                total_time = (time.time() - start_time) * 1000
                logger.info(f"✅ Complete: {total_time:.0f}ms, {total_phrases} phrases")
            else:
                logger.error("❌ No Gemini API key")
                yield "Configuration error."
        except asyncio.CancelledError:
            logger.info(f"🛑 Cancelled: {session_id}")
            raise
        except Exception as e:
            logger.error(f"❌ Streaming error: {e}")
            yield "I'm experiencing difficulties."
    async def _stream_gemini_ultra_fast(self, prompt: str) -> AsyncIterator[str]:
        try:
            from google import genai
            client = genai.Client(api_key=config.services.gemini_api_key)
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=150,
                    top_p=0.85,
                    top_k=25,
                ),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"❌ Gemini error: {e}")
            from google import genai
            client = genai.Client(api_key=config.services.gemini_api_key)
            for chunk in client.models.generate_content_stream(
                model='gemini-2.0-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=150
                ),
            ):
                if chunk.text:
                    yield chunk.text
    async def _safe_tts_publish(self, tts_callback: Callable, phrase: str, session_id: str):
        try:
            await tts_callback(phrase)
        except Exception as e:
            logger.warning(f"TTS publish failed: {e}")
    def get_metrics(self) -> Dict[str, Any]:
        return self.metrics.get_stats()

streaming_ai_service = StreamingAIService()
