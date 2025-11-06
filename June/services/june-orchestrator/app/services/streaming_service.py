import re
import time

class UltraFastPhraseBuffer:
    """Punctuation-based TTS sentence chunker (production best practice)"""
    def __init__(self, min_length=25, timeout_ms=150):
        self.buffer = ""
        self.token_count = 0
        self.last_token_time = time.time()
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.sentence_end_re = re.compile(r'[.!?…。！？]+')
        self.min_length = min_length
        self.timeout_ms = timeout_ms
    
    def add_token(self, token: str) -> str | None:
        """
        Add token, yield sentence/fragments only at strong boundaries and only if chunk is long enough.
        """
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

    def flush_remaining(self):
        if self.buffer.strip():
            phrase = self.buffer.strip()
            self.buffer = ""
            self.token_count = 0
            self.phrase_count += 1
            return phrase
        return None

    def get_phrase_count(self):
        return self.phrase_count

    def reset(self):
        self.buffer = ""
        self.token_count = 0
        self.phrase_count = 0
        self.first_phrase_sent = False
        self.last_token_time = time.time()


class StreamingAIService:
    def __init__(self):
        pass
    # ... rest of your AI streaming logic here ...

# Global instance (required by routes and RT engine)
streaming_ai_service = StreamingAIService()
