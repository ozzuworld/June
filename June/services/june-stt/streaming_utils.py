#!/usr/bin/env python3
"""
Streaming utilities for partial STT transcription
"""
import logging
import time
from typing import Optional, Dict, Any
from collections import deque
import numpy as np

logger = logging.getLogger("streaming-stt")

class PartialTranscriptStreamer:
    """Manages streaming partial transcripts for real-time voice processing"""
    
    def __init__(self, chunk_duration_ms: int = 150, min_speech_ms: int = 200):
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
        self.ultra_fast_mode = True
        self.consecutive_similar = 0
        
    def add_audio_chunk(self, audio: np.ndarray) -> bool:
        """Add audio chunk and return if ready for partial processing"""
        self.partial_buffer.extend(audio)
        self.total_samples += len(audio)
        
        # Ultra-fast mode for first partial
        if self.ultra_fast_mode and not self.last_partial_text:
            min_samples_for_first = self.min_speech_samples // 2
            return len(self.partial_buffer) >= min_samples_for_first
        
        return len(self.partial_buffer) >= self.chunk_samples
        
    def get_partial_audio(self) -> Optional[np.ndarray]:
        """Get audio for partial transcription"""
        min_samples = self.chunk_samples
        
        if self.ultra_fast_mode and not self.last_partial_text:
            min_samples = self.min_speech_samples // 2
            
        if len(self.partial_buffer) < min_samples:
            return None
            
        chunk_size = min(len(self.partial_buffer), self.chunk_samples)
        chunk = np.array(list(self.partial_buffer)[:chunk_size])
        
        # 60% overlap for context
        overlap_samples = int(chunk_size * 0.6)
        for _ in range(chunk_size - overlap_samples):
            if self.partial_buffer:
                self.partial_buffer.popleft()
                
        return chunk
        
    def should_emit_partial(self, new_text: str) -> bool:
        """Check if partial should be emitted"""
        if not new_text or len(new_text.strip()) < 2:
            return False
        
        new_text_clean = new_text.strip().lower()
        last_text_clean = self.last_partial_text.strip().lower()
        
        # Always emit first partial
        if not self.last_partial_text:
            return True
            
        # Don't emit identical partials
        if new_text_clean == last_text_clean:
            self.consecutive_similar += 1
            if self.consecutive_similar > 2:
                return False
            return False
        
        self.consecutive_similar = 0
            
        # Smart growth detection
        if last_text_clean and new_text_clean.startswith(last_text_clean):
            added_text = new_text_clean[len(last_text_clean):].strip()
            
            added_words = added_text.split()
            if len(added_words) == 1:
                important_words = {'what', 'how', 'why', 'when', 'where', 'can', 'will', 'you', 'the'}
                if len(added_words[0]) <= 3 and added_words[0] not in important_words:
                    return False
                    
            if len(added_text) < 2:
                return False
        
        # Filter noise words
        noise_words = {'uh', 'um', 'ah', 'eh', 'mm', 'hmm', 'er', 'oh'}
        if new_text_clean in noise_words:
            return False
            
        # Filter short fragments
        words = new_text_clean.split()
        if len(words) == 1 and len(words[0]) <= 2:
            return False
            
        return True
        
    def update_partial_text(self, text: str):
        """Update tracking of last partial text"""
        self.last_partial_text = text
        
        # Disable ultra-fast mode after first successful partial
        if self.ultra_fast_mode and text:
            self.ultra_fast_mode = False
        
    def reset(self):
        """Reset state for new utterance"""
        self.partial_buffer.clear()
        self.last_partial_text = ""
        self.speech_detected = False
        self.total_samples = 0
        self.ultra_fast_mode = True
        self.consecutive_similar = 0

class SentenceSegmenter:
    """Segments streaming text into complete sentences for TTS"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}
        self.min_sentence_length = 6
        self.max_buffer_length = 160
        
    def add_text(self, text: str) -> list[str]:
        """Add text and return complete sentences ready for TTS"""
        self.buffer += text
        sentences = []
        
        # Process questions immediately
        question_endings = {'?', '？'}
        for i, char in enumerate(self.buffer):
            if char in question_endings:
                sentence = self.buffer[:i+1].strip()
                if len(sentence) >= 4:
                    sentences.append(sentence)
                    self.buffer = self.buffer[i+1:].strip()
                    break
        
        # Process complete statements
        if not sentences:
            for i, char in enumerate(self.buffer):
                if char in self.sentence_endings:
                    sentence = self.buffer[:i+1].strip()
                    if len(sentence) >= self.min_sentence_length:
                        sentences.append(sentence)
                        self.buffer = self.buffer[i+1:].strip()
                        break
                    
        # Handle buffer overflow
        if len(self.buffer) > self.max_buffer_length:
            break_points = [
                ('? ', 2), ('! ', 2), ('. ', 2), (', ', 1),
                (' and ', 1), (' but ', 1), (' or ', 1), (' so ', 1),
                (' that ', 1), (' which ', 1), (' when ', 1),
            ]
            
            best_break = -1
            best_priority = 0
            
            for bp_text, priority in break_points:
                pos = self.buffer.rfind(bp_text, 60, 140)
                if pos > best_break and priority >= best_priority:
                    best_break = pos + len(bp_text) - 1
                    best_priority = priority
            
            if best_break > 0:
                sentence = self.buffer[:best_break+1].strip()
                self.buffer = self.buffer[best_break+1:].strip()
                if len(sentence) >= self.min_sentence_length:
                    sentences.append(sentence)
            else:
                words = self.buffer[:130].split()
                if len(words) > 2:
                    sentence = ' '.join(words[:-1])
                    remaining = ' '.join(words[-1:]) + self.buffer[130:]
                    self.buffer = remaining
                    if len(sentence) >= self.min_sentence_length:
                        sentences.append(sentence)
                    
        return sentences
        
    def flush_remaining(self) -> Optional[str]:
        """Get any remaining text as final sentence"""
        if self.buffer.strip() and len(self.buffer.strip()) >= 4:
            sentence = self.buffer.strip()
            self.buffer = ""
            return sentence
        return None
        
    def reset(self):
        """Reset segmenter state"""
        self.buffer = ""

class StreamingMetrics:
    """Performance metrics for streaming"""
    
    def __init__(self):
        self.partial_count = 0
        self.final_count = 0
        self.first_partial_times = []
        self.partial_intervals = []
        self.ultra_fast_achievements = 0
        self.last_partial_time = None
        self.session_start = time.time()
        self.openai_competitive_count = 0
        self.google_competitive_count = 0
        
    def record_partial(self, processing_time_ms: float, from_speech_start_ms: float = None):
        """Record partial transcript metrics"""
        now = time.time()
        self.partial_count += 1
        
        if self.partial_count == 1 or (self.last_partial_time is None):
            self.first_partial_times.append(processing_time_ms)
            
            if from_speech_start_ms and from_speech_start_ms < 200:
                self.ultra_fast_achievements += 1
            
            if processing_time_ms < 300:
                self.openai_competitive_count += 1
            if processing_time_ms < 500:
                self.google_competitive_count += 1

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
        
        openai_competitive_rate = (self.openai_competitive_count / max(1, len(self.first_partial_times))) * 100
        google_competitive_rate = (self.google_competitive_count / max(1, len(self.first_partial_times))) * 100
        ultra_fast_rate = (self.ultra_fast_achievements / max(1, len(self.first_partial_times))) * 100
        
        if avg_first_partial < 300:
            performance_tier = "OPENAI_COMPETITIVE"
        elif avg_first_partial < 500:
            performance_tier = "GOOGLE_COMPETITIVE"
        elif avg_first_partial < 700:
            performance_tier = "INDUSTRY_STANDARD"
        else:
            performance_tier = "NEEDS_OPTIMIZATION"
        
        return {
            "partial_transcripts": self.partial_count,
            "final_transcripts": self.final_count,
            "avg_first_partial_ms": round(avg_first_partial, 1),
            "avg_partial_interval_ms": round(avg_interval, 1),
            "streaming_efficiency": round(self.partial_count / max(1, self.final_count), 2),
            "performance": {
                "ultra_fast_achievements": self.ultra_fast_achievements,
                "ultra_fast_rate_percent": round(ultra_fast_rate, 1),
                "openai_competitive_rate_percent": round(openai_competitive_rate, 1),
                "google_competitive_rate_percent": round(google_competitive_rate, 1),
                "performance_tier": performance_tier,
                "session_duration_minutes": round((time.time() - self.session_start) / 60, 1),
            }
        }

streaming_metrics = StreamingMetrics()