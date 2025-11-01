#!/usr/bin/env python3
"""
Streaming utilities for partial STT transcription
Enables real-time partial transcript emission for lower latency
"""
import logging
import asyncio
import time
from typing import Optional, AsyncIterator, Dict, Any
from collections import deque
import numpy as np

logger = logging.getLogger("streaming-stt")


class PartialTranscriptStreamer:
    """Manages streaming partial transcripts for real-time voice processing"""
    
    def __init__(self, chunk_duration_ms: int = 200, min_speech_ms: int = 500):
        self.chunk_duration_ms = chunk_duration_ms
        self.min_speech_ms = min_speech_ms
        self.sample_rate = 16000
        self.chunk_samples = int((chunk_duration_ms / 1000) * self.sample_rate)
        self.min_speech_samples = int((min_speech_ms / 1000) * self.sample_rate)
        
        # State tracking
        self.partial_buffer = deque()
        self.last_partial_text = ""
        self.speech_detected = False
        self.total_samples = 0
        
    def add_audio_chunk(self, audio: np.ndarray) -> bool:
        """Add audio chunk and return if ready for partial processing"""
        self.partial_buffer.extend(audio)
        self.total_samples += len(audio)
        
        # Check if we have enough for partial transcription
        return len(self.partial_buffer) >= self.chunk_samples
        
    def get_partial_audio(self) -> Optional[np.ndarray]:
        """Get audio for partial transcription"""
        if len(self.partial_buffer) < self.chunk_samples:
            return None
            
        # Extract chunk for processing
        chunk = np.array(list(self.partial_buffer)[:self.chunk_samples])
        
        # Keep overlap for context (50% overlap)
        overlap_samples = self.chunk_samples // 2
        # Remove processed samples but keep overlap
        for _ in range(self.chunk_samples - overlap_samples):
            if self.partial_buffer:
                self.partial_buffer.popleft()
                
        return chunk
        
    def should_emit_partial(self, new_text: str) -> bool:
        """Check if partial should be emitted (avoid duplicate/similar partials)"""
        if not new_text or len(new_text) < 3:
            return False
            
        # Don't emit if very similar to last partial
        if new_text == self.last_partial_text:
            return False
            
        # Don't emit if just adding single words to previous partial
        if self.last_partial_text and new_text.startswith(self.last_partial_text):
            added_text = new_text[len(self.last_partial_text):].strip()
            if len(added_text.split()) == 1:  # Only one word added
                return False
                
        return True
        
    def update_partial_text(self, text: str):
        """Update tracking of last partial text"""
        self.last_partial_text = text
        
    def reset(self):
        """Reset state for new utterance"""
        self.partial_buffer.clear()
        self.last_partial_text = ""
        self.speech_detected = False
        self.total_samples = 0


class SentenceSegmenter:
    """Segments streaming text into complete sentences for TTS"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}  # Multi-language
        self.min_sentence_length = 10
        
    def add_text(self, text: str) -> list[str]:
        """Add text and return complete sentences ready for TTS"""
        self.buffer += text
        sentences = []
        
        # Find sentence boundaries
        for i, char in enumerate(self.buffer):
            if char in self.sentence_endings:
                sentence = self.buffer[:i+1].strip()
                if len(sentence) >= self.min_sentence_length:
                    sentences.append(sentence)
                    self.buffer = self.buffer[i+1:]
                    break
                    
        # Handle buffer overflow (send partial if too long)
        if len(self.buffer) > 200:
            # Find last space to break cleanly
            last_space = self.buffer.rfind(' ', 100, 180)
            if last_space > 0:
                sentences.append(self.buffer[:last_space].strip())
                self.buffer = self.buffer[last_space:].strip()
            else:
                # Force break at 150 chars
                sentences.append(self.buffer[:150].strip())
                self.buffer = self.buffer[150:].strip()
                
        return sentences
        
    def flush_remaining(self) -> Optional[str]:
        """Get any remaining text as final sentence"""
        if self.buffer.strip() and len(self.buffer.strip()) >= self.min_sentence_length:
            sentence = self.buffer.strip()
            self.buffer = ""
            return sentence
        return None
        
    def reset(self):
        """Reset segmenter state"""
        self.buffer = ""


# Performance metrics for streaming
class StreamingMetrics:
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
            "streaming_efficiency": round(self.partial_count / max(1, self.final_count), 2)
        }


# Global streaming components
streaming_metrics = StreamingMetrics()