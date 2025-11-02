#!/usr/bin/env python3
"""
SOTA Streaming utilities for partial STT transcription
Enables real-time partial transcript emission for competitive latency
Optimized for ultra-fast first partial and smooth continuous streaming
"""
import logging
import asyncio
import time
from typing import Optional, AsyncIterator, Dict, Any
from collections import deque
import numpy as np

logger = logging.getLogger("sota-streaming-stt")


class PartialTranscriptStreamer:
    """SOTA: Manages ultra-responsive streaming partial transcripts for competitive voice AI"""
    
    def __init__(self, chunk_duration_ms: int = 150, min_speech_ms: int = 200):  # SOTA: Faster defaults
        self.chunk_duration_ms = chunk_duration_ms
        self.min_speech_ms = min_speech_ms
        self.sample_rate = 16000
        self.chunk_samples = int((chunk_duration_ms / 1000) * self.sample_rate)
        self.min_speech_samples = int((min_speech_ms / 1000) * self.sample_rate)
        
        # SOTA: Enhanced state tracking for competitive performance
        self.partial_buffer = deque()
        self.last_partial_text = ""
        self.speech_detected = False
        self.total_samples = 0
        self.ultra_fast_mode = True  # SOTA: Enable ultra-fast first partial
        self.consecutive_similar = 0  # SOTA: Track repetitive partials
        
        logger.debug(f"⚡ SOTA: Created ultra-fast partial streamer (chunk={chunk_duration_ms}ms, min_speech={min_speech_ms}ms)")
        
    def add_audio_chunk(self, audio: np.ndarray) -> bool:
        """SOTA: Add audio chunk with ultra-responsive processing readiness check"""
        self.partial_buffer.extend(audio)
        self.total_samples += len(audio)
        
        # SOTA: Ultra-fast mode for first partial (lower threshold)
        if self.ultra_fast_mode and not self.last_partial_text:
            min_samples_for_first = self.min_speech_samples // 2  # 50% threshold for first partial
            return len(self.partial_buffer) >= min_samples_for_first
        
        # Regular streaming check
        return len(self.partial_buffer) >= self.chunk_samples
        
    def get_partial_audio(self) -> Optional[np.ndarray]:
        """SOTA: Get optimized audio for ultra-fast partial transcription"""
        min_samples = self.chunk_samples
        
        # SOTA: Ultra-fast mode uses smaller chunks for first partial
        if self.ultra_fast_mode and not self.last_partial_text:
            min_samples = self.min_speech_samples // 2
            
        if len(self.partial_buffer) < min_samples:
            return None
            
        # SOTA: Extract optimal chunk for processing
        chunk_size = min(len(self.partial_buffer), self.chunk_samples)
        chunk = np.array(list(self.partial_buffer)[:chunk_size])
        
        # SOTA: Smart overlap for context preservation (60% for better accuracy)
        overlap_samples = int(chunk_size * 0.6)
        
        # Remove processed samples but keep overlap
        for _ in range(chunk_size - overlap_samples):
            if self.partial_buffer:
                self.partial_buffer.popleft()
                
        return chunk
        
    def should_emit_partial(self, new_text: str) -> bool:
        """SOTA: Enhanced partial emission logic for competitive responsiveness"""
        if not new_text or len(new_text.strip()) < 2:
            return False
        
        new_text_clean = new_text.strip().lower()
        last_text_clean = self.last_partial_text.strip().lower()
        
        # SOTA: Always emit first partial (ultra-fast mode)
        if not self.last_partial_text:
            logger.debug(f"🚀 SOTA: First partial emission: '{new_text}'")
            return True
            
        # SOTA: Don't emit identical partials
        if new_text_clean == last_text_clean:
            self.consecutive_similar += 1
            if self.consecutive_similar > 2:  # Allow some repetition, then block
                logger.debug(f"🚫 SOTA: Blocking repetitive partial: '{new_text}'")
                return False
            return False
        
        self.consecutive_similar = 0  # Reset repetition counter
            
        # SOTA: Smart growth detection for meaningful updates
        if last_text_clean and new_text_clean.startswith(last_text_clean):
            added_text = new_text_clean[len(last_text_clean):].strip()
            
            # SOTA: Allow single word additions if meaningful
            added_words = added_text.split()
            if len(added_words) == 1:
                # Allow single word if it's substantial (>3 chars) or important
                important_words = {'what', 'how', 'why', 'when', 'where', 'can', 'will', 'you', 'the'}
                if len(added_words[0]) <= 3 and added_words[0] not in important_words:
                    logger.debug(f"🚫 SOTA: Skipping trivial single word: '{added_words[0]}'")
                    return False
                    
            # SOTA: Require at least 2 new characters for updates
            if len(added_text) < 2:
                return False
        
        # SOTA: Enhanced filtering for noise words
        noise_words = {'uh', 'um', 'ah', 'eh', 'mm', 'hmm', 'er', 'oh'}
        if new_text_clean in noise_words:
            logger.debug(f"😫 SOTA: Filtered noise word: '{new_text_clean}'")
            return False
            
        # SOTA: Filter very short or fragmented partials
        words = new_text_clean.split()
        if len(words) == 1 and len(words[0]) <= 2:
            logger.debug(f"🚫 SOTA: Filtered short fragment: '{new_text_clean}'")
            return False
            
        logger.debug(f"✅ SOTA: Partial emission approved: '{new_text}'")
        return True
        
    def update_partial_text(self, text: str):
        """SOTA: Update tracking with performance optimization indicators"""
        old_text = self.last_partial_text
        self.last_partial_text = text
        
        # SOTA: Disable ultra-fast mode after first successful partial
        if self.ultra_fast_mode and text:
            self.ultra_fast_mode = False
            logger.debug(f"🚀 SOTA: Ultra-fast mode complete, switching to optimized streaming")
        
    def reset(self):
        """SOTA: Reset state for new utterance with performance tracking"""
        logger.debug("🔄 SOTA: Resetting partial streamer for new utterance")
        self.partial_buffer.clear()
        self.last_partial_text = ""
        self.speech_detected = False
        self.total_samples = 0
        self.ultra_fast_mode = True  # Re-enable for next utterance
        self.consecutive_similar = 0


class SentenceSegmenter:
    """SOTA: Enhanced sentence segmentation for smooth TTS streaming"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}  # Multi-language support
        self.min_sentence_length = 8  # SOTA: More aggressive (was 10)
        self.max_buffer_length = 180  # SOTA: Shorter for faster emission
        
    def add_text(self, text: str) -> list[str]:
        """SOTA: Add text with enhanced sentence detection for competitive TTS latency"""
        self.buffer += text
        sentences = []
        
        # SOTA: Enhanced sentence boundary detection
        for i, char in enumerate(self.buffer):
            if char in self.sentence_endings:
                sentence = self.buffer[:i+1].strip()
                if len(sentence) >= self.min_sentence_length:
                    sentences.append(sentence)
                    self.buffer = self.buffer[i+1:].strip()
                    logger.debug(f"📝 SOTA: Complete sentence detected: '{sentence[:30]}...'")
                    break
                    
        # SOTA: Handle buffer overflow more aggressively
        if len(self.buffer) > self.max_buffer_length:
            # Find optimal break point
            break_points = ['. ', '! ', '? ', ', ', '; ', ' and ', ' but ', ' or ']
            best_break = -1
            
            for bp in break_points:
                pos = self.buffer.rfind(bp, 80, 150)  # Look in optimal range
                if pos > best_break:
                    best_break = pos + len(bp) - 1
            
            if best_break > 0:
                sentence = self.buffer[:best_break+1].strip()
                self.buffer = self.buffer[best_break+1:].strip()
                if len(sentence) >= self.min_sentence_length:
                    sentences.append(sentence)
                    logger.debug(f"⚡ SOTA: Forced sentence break: '{sentence[:30]}...'")
            else:
                # Last resort: break at word boundary
                words = self.buffer[:150].split()
                if len(words) > 3:  # Keep some context
                    sentence = ' '.join(words[:-1])
                    remaining = ' '.join(words[-1:]) + self.buffer[150:]
                    self.buffer = remaining
                    sentences.append(sentence)
                    logger.debug(f"🔄 SOTA: Word boundary break: '{sentence[:30]}...'")
                    
        return sentences
        
    def flush_remaining(self) -> Optional[str]:
        """SOTA: Get remaining text with lower threshold for final flush"""
        if self.buffer.strip() and len(self.buffer.strip()) >= 6:  # SOTA: Lower threshold
            sentence = self.buffer.strip()
            self.buffer = ""
            logger.debug(f"📝 SOTA: Final flush: '{sentence[:30]}...'")
            return sentence
        return None
        
    def reset(self):
        """Reset segmenter state"""
        self.buffer = ""


# SOTA Performance metrics for competitive voice AI
class StreamingMetrics:
    """SOTA: Enhanced metrics tracking for competitive performance monitoring"""
    
    def __init__(self):
        self.partial_count = 0
        self.final_count = 0
        self.first_partial_times = []
        self.partial_intervals = []
        self.ultra_fast_achievements = 0  # SOTA: Count sub-200ms first partials
        self.last_partial_time = None
        self.session_start = time.time()
        
        # SOTA: Competitive benchmarking
        self.openai_competitive_count = 0  # <300ms responses
        self.google_competitive_count = 0  # <500ms responses
        
    def record_partial(self, processing_time_ms: float, from_speech_start_ms: float = None):
        """SOTA: Record partial with competitive benchmarking"""
        now = time.time()
        self.partial_count += 1
        
        # SOTA: Track first partial performance
        if self.partial_count == 1 or (self.last_partial_time is None):
            self.first_partial_times.append(processing_time_ms)
            
            # SOTA: Track ultra-fast achievements
            if from_speech_start_ms and from_speech_start_ms < 200:
                self.ultra_fast_achievements += 1
                logger.info(f"🚀 SOTA ULTRA-FAST achieved: {from_speech_start_ms:.0f}ms from speech start")
            
            # SOTA: Competitive benchmarking
            if processing_time_ms < 300:
                self.openai_competitive_count += 1
            if processing_time_ms < 500:
                self.google_competitive_count += 1

        # SOTA: Track streaming intervals
        if self.last_partial_time:
            interval = (now - self.last_partial_time) * 1000
            self.partial_intervals.append(interval)
            
        self.last_partial_time = now
        
    def record_final(self):
        """Record final transcript completion"""
        self.final_count += 1
        self.last_partial_time = None
        
    def get_stats(self) -> Dict[str, Any]:
        """SOTA: Get comprehensive streaming performance statistics with competitive analysis"""
        avg_first_partial = sum(self.first_partial_times) / len(self.first_partial_times) if self.first_partial_times else 0
        avg_interval = sum(self.partial_intervals) / len(self.partial_intervals) if self.partial_intervals else 0
        
        # SOTA: Competitive performance analysis
        openai_competitive_rate = (self.openai_competitive_count / max(1, len(self.first_partial_times))) * 100
        google_competitive_rate = (self.google_competitive_count / max(1, len(self.first_partial_times))) * 100
        ultra_fast_rate = (self.ultra_fast_achievements / max(1, len(self.first_partial_times))) * 100
        
        # SOTA: Determine performance tier
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
            "sota_performance": {
                "ultra_fast_achievements": self.ultra_fast_achievements,
                "ultra_fast_rate_percent": round(ultra_fast_rate, 1),
                "openai_competitive_rate_percent": round(openai_competitive_rate, 1),
                "google_competitive_rate_percent": round(google_competitive_rate, 1),
                "performance_tier": performance_tier,
                "session_duration_minutes": round((time.time() - self.session_start) / 60, 1),
            },
            "benchmarks": {
                "openai_realtime_target_ms": 300,
                "google_gemini_target_ms": 500,
                "our_average_ms": round(avg_first_partial, 1),
                "competitive_status": "ACHIEVED" if performance_tier in ["OPENAI_COMPETITIVE", "GOOGLE_COMPETITIVE"] else "IN_PROGRESS"
            }
        }


class SentenceSegmenter:
    """SOTA: Ultra-responsive sentence segmentation for competitive TTS streaming"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = {'.', '!', '?', '。', '！', '？'}  # Multi-language
        self.min_sentence_length = 6  # SOTA: More aggressive (was 10)
        self.max_buffer_length = 160  # SOTA: Shorter for ultra-fast emission
        
    def add_text(self, text: str) -> list[str]:
        """SOTA: Ultra-responsive sentence detection for competitive TTS latency"""
        self.buffer += text
        sentences = []
        
        # SOTA: Enhanced sentence boundary detection with question priority
        question_endings = {'?', '？'}
        statement_endings = {'.', '!', '。', '！'}
        
        # Priority 1: Process questions immediately (most important for voice AI)
        for i, char in enumerate(self.buffer):
            if char in question_endings:
                sentence = self.buffer[:i+1].strip()
                if len(sentence) >= 4:  # Very low threshold for questions
                    sentences.append(sentence)
                    self.buffer = self.buffer[i+1:].strip()
                    logger.debug(f"❓ SOTA: Question detected immediately: '{sentence[:30]}...'")
                    break
        
        # Priority 2: Process complete statements
        if not sentences:  # Only if no question was found
            for i, char in enumerate(self.buffer):
                if char in statement_endings:
                    sentence = self.buffer[:i+1].strip()
                    if len(sentence) >= self.min_sentence_length:
                        sentences.append(sentence)
                        self.buffer = self.buffer[i+1:].strip()
                        logger.debug(f"📝 SOTA: Statement complete: '{sentence[:30]}...'")
                        break
                    
        # SOTA: Ultra-aggressive buffer overflow handling
        if len(self.buffer) > self.max_buffer_length:
            # Enhanced break point detection
            break_points = [
                ('? ', 2),   # Questions get highest priority
                ('! ', 2),   # Exclamations
                ('. ', 2),   # Statements
                (', ', 1),   # Commas
                (' and ', 1), (' but ', 1), (' or ', 1), (' so ', 1),  # Conjunctions
                (' that ', 1), (' which ', 1), (' when ', 1),  # Relative clauses
            ]
            
            best_break = -1
            best_priority = 0
            
            for bp_text, priority in break_points:
                pos = self.buffer.rfind(bp_text, 60, 140)  # SOTA: Narrower optimal range
                if pos > best_break and priority >= best_priority:
                    best_break = pos + len(bp_text) - 1
                    best_priority = priority
            
            if best_break > 0:
                sentence = self.buffer[:best_break+1].strip()
                self.buffer = self.buffer[best_break+1:].strip()
                if len(sentence) >= self.min_sentence_length:
                    sentences.append(sentence)
                    logger.debug(f"⚡ SOTA: Smart break: '{sentence[:30]}...'")
            else:
                # SOTA: Force break at word boundary with context preservation
                words = self.buffer[:130].split()  # SOTA: Shorter chunk
                if len(words) > 2:  # Keep minimal context
                    sentence = ' '.join(words[:-1])
                    remaining = ' '.join(words[-1:]) + self.buffer[130:]
                    self.buffer = remaining
                    if len(sentence) >= self.min_sentence_length:
                        sentences.append(sentence)
                        logger.debug(f"🔄 SOTA: Forced word break: '{sentence[:30]}...'")
                    
        return sentences
        
    def flush_remaining(self) -> Optional[str]:
        """SOTA: Enhanced final flush with lower threshold"""
        if self.buffer.strip() and len(self.buffer.strip()) >= 4:  # SOTA: Much lower threshold
            sentence = self.buffer.strip()
            self.buffer = ""
            logger.debug(f"📝 SOTA: Final flush (low threshold): '{sentence[:30]}...'")
            return sentence
        return None
        
    def reset(self):
        """Reset segmenter state"""
        self.buffer = ""


# SOTA: Global streaming components with competitive performance tracking
streaming_metrics = StreamingMetrics()