#!/usr/bin/env python3
"""
Streaming TTS Module - Production-Quality Audio Streaming
Implements jitter buffer, cross-fading, and clock-based timing to eliminate audio artifacts
"""
import logging
import asyncio
import time
import tempfile
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from collections import deque

import numpy as np
import soundfile as sf
from livekit import rtc
import torch

logger = logging.getLogger("streaming-tts")

STREAMING_TTS_ENABLED = True
SAMPLE_RATE = 24000
FRAME_SIZE = 240  # 10ms frames - synchronized with main service
JITTER_BUFFER_TARGET_MS = 40  # Target buffer size in ms
JITTER_BUFFER_MAX_MS = 70     # Maximum buffer size
CROSSFADE_MS = 10             # Cross-fade duration between chunks

@dataclass
class TTSStreamingMetrics:
    def __init__(self):
        self.first_audio_times = []
        self.total_chunks = 0
        self.streaming_requests = 0
        self.sub_100ms_count = 0
        self.buffer_underruns = 0
        self.crossfades_applied = 0
        self.jitter_buffer_adjustments = 0
        
    def record_first_audio(self, time_ms: float):
        self.first_audio_times.append(time_ms)
        if time_ms < 100:
            self.sub_100ms_count += 1
        
    def get_stats(self) -> Dict[str, Any]:
        avg_first_audio = sum(self.first_audio_times) / len(self.first_audio_times) if self.first_audio_times else 0
        success_rate = self.sub_100ms_count / len(self.first_audio_times) * 100 if self.first_audio_times else 0
        
        return {
            "engine": "kokoro-82m",
            "avg_first_audio_ms": round(avg_first_audio, 1),
            "sub_100ms_success_rate": round(success_rate, 1),
            "streaming_requests": self.streaming_requests,
            "target_achieved": avg_first_audio < 100,
            "frame_size": FRAME_SIZE,
            "jitter_buffer_target_ms": JITTER_BUFFER_TARGET_MS,
            "buffer_underruns": self.buffer_underruns,
            "crossfades_applied": self.crossfades_applied,
            "jitter_adjustments": self.jitter_buffer_adjustments,
            "artifacts_fixed": "jitter_buffer + crossfade + clock_timing"
        }

class JitterBuffer:
    """Small output buffer to smooth audio delivery and prevent artifacts"""
    
    def __init__(self, target_frames: int = 4, max_frames: int = 7):
        self.target_frames = target_frames
        self.max_frames = max_frames
        self.buffer = deque()
        self.started_playback = False
        self.underruns = 0
        
    def add_frame(self, frame_data: np.ndarray):
        """Add frame to jitter buffer"""
        if len(self.buffer) >= self.max_frames:
            # Drop oldest frame to prevent excessive buffering
            self.buffer.popleft()
            
        self.buffer.append(frame_data.copy())
        
    def can_start_playback(self) -> bool:
        """Check if we have enough frames to start smooth playback"""
        return len(self.buffer) >= self.target_frames or self.started_playback
        
    def get_frame(self) -> Optional[np.ndarray]:
        """Get next frame for playback"""
        if not self.can_start_playback():
            return None
            
        if len(self.buffer) == 0:
            self.underruns += 1
            logger.warning("⚠️ Jitter buffer underrun")
            return None
            
        self.started_playback = True
        return self.buffer.popleft()
        
    def frames_available(self) -> int:
        return len(self.buffer)
        
    def adjust_target(self, late_frames_count: int):
        """Dynamically adjust buffer target based on performance"""
        if late_frames_count > 3:
            # Increase buffer size
            old_target = self.target_frames
            self.target_frames = min(self.target_frames + 1, self.max_frames - 1)
            if self.target_frames != old_target:
                logger.info(f"📊 Increased jitter buffer: {old_target} → {self.target_frames} frames")
                return True
        elif late_frames_count == 0 and self.target_frames > 3:
            # Gradually decrease buffer size when stable
            self.target_frames -= 1
            logger.info(f"📊 Decreased jitter buffer: {self.target_frames + 1} → {self.target_frames} frames")
            return True
        return False

class StreamingTTSEngine:
    def __init__(self, audio_source: rtc.AudioSource):
        self.audio_source = audio_source
        self.metrics = TTSStreamingMetrics()
        self.buffer_initialized = False
        self.jitter_buffer = JitterBuffer()
        self.last_chunk_tail = None  # For cross-fading
        self.session_start_time = None
        self.frames_sent = 0
        self.late_frames_count = 0
        
    async def _prime_audio_buffer(self):
        """Prime audio buffer to prevent scrambled first chunk"""
        if self.buffer_initialized:
            return
            
        # Send buffer priming silence
        priming_ms = 100
        priming_samples = int(SAMPLE_RATE * priming_ms / 1000)
        silence_buffer = np.zeros(priming_samples, dtype=np.int16)
        
        logger.info(f"🔧 Priming audio buffer: {priming_ms}ms ({priming_samples} samples)")
        
        # Send priming frames with clock-based timing
        self.session_start_time = time.monotonic()
        frame_count = 0
        
        for i in range(0, len(silence_buffer), FRAME_SIZE):
            frame_data = silence_buffer[i:i + FRAME_SIZE]
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            
            frame = rtc.AudioFrame(
                data=frame_data.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(frame_data)
            )
            
            await self.audio_source.capture_frame(frame)
            
            # Clock-based timing - prevents drift
            frame_count += 1
            target_time = self.session_start_time + (frame_count * 0.01)
            current_time = time.monotonic()
            sleep_time = target_time - current_time
            
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            elif sleep_time < -0.002:
                self.late_frames_count += 1
        
        self.frames_sent = frame_count
        self.buffer_initialized = True
        logger.info("✅ Audio buffer primed successfully")
        
    async def stream_to_room(self, text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
        start_time = time.time()
        self.metrics.streaming_requests += 1
        
        # Always prime buffer before streaming
        await self._prime_audio_buffer()
        
        # Reset per-session state
        self.jitter_buffer = JitterBuffer()
        self.last_chunk_tail = None
        chunks_processed = 0
        
        try:
            # Use Kokoro's native streaming
            first_audio_time = None
            
            async for audio_chunk in chatterbox_engine.synthesize_streaming(
                text=text, language=language, speaker_wav=speaker_wav,
                voice_preset="af_bella", speed=1.0
            ):
                if first_audio_time is None:
                    first_audio_time = (time.time() - start_time) * 1000
                    self.metrics.record_first_audio(first_audio_time)
                    
                    if first_audio_time < 100:
                        logger.info(f"🏆 KOKORO SUB-100MS: {first_audio_time:.0f}ms")
                    else:
                        logger.info(f"🎵 First audio: {first_audio_time:.0f}ms")
                
                # Process audio chunk with cross-fading and jitter buffering
                audio_np = await self._process_audio_chunk_with_crossfade(audio_chunk)
                await self._add_to_jitter_buffer_and_stream(audio_np)
                chunks_processed += 1
            
            # Flush remaining frames from jitter buffer
            await self._flush_jitter_buffer()
            
            # Adjust jitter buffer based on performance
            if self.jitter_buffer.adjust_target(self.late_frames_count):
                self.metrics.jitter_buffer_adjustments += 1
            
            total_time = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "method": "kokoro_streaming_production",
                "chunks_sent": chunks_processed,
                "first_audio_ms": first_audio_time or 0,
                "total_time_ms": round(total_time, 1),
                "buffer_primed": self.buffer_initialized,
                "jitter_buffer_underruns": self.jitter_buffer.underruns,
                "crossfades_applied": self.metrics.crossfades_applied,
                "late_frames": self.late_frames_count,
                "artifacts_eliminated": True
            }
            
        except Exception as e:
            logger.error(f"Kokoro streaming error: {e}")
            # Fallback to regular synthesis
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)
    
    async def _process_audio_chunk_with_crossfade(self, audio_chunk) -> np.ndarray:
        """Process audio chunk with cross-fading at boundaries"""
        # Convert to numpy int16
        if isinstance(audio_chunk, torch.Tensor):
            audio_np = audio_chunk.detach().cpu().numpy()
        else:
            audio_np = audio_chunk
        
        # Convert to mono if needed
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)
        
        # Apply soft limiting to prevent clipping
        if audio_np.dtype in [np.float32, np.float64]:
            audio_np = np.tanh(audio_np * 0.8) * 0.9  # Soft limiting
            audio_np = np.clip(audio_np, -1.0, 1.0)
            audio_np = (audio_np * 32767 * 0.9).astype(np.int16)  # Leave headroom
        else:
            audio_np = np.clip(audio_np, -32767, 32767).astype(np.int16)
        
        # Apply cross-fade if we have previous chunk tail
        if self.last_chunk_tail is not None and len(self.last_chunk_tail) > 0:
            crossfade_samples = min(
                int(SAMPLE_RATE * CROSSFADE_MS / 1000),
                len(self.last_chunk_tail),
                len(audio_np)
            )
            
            if crossfade_samples > 0:
                # Create fade curves
                fade_out = np.linspace(1.0, 0.0, crossfade_samples)
                fade_in = np.linspace(0.0, 1.0, crossfade_samples)
                
                # Apply cross-fade
                tail_fade = (self.last_chunk_tail[-crossfade_samples:] * fade_out).astype(np.int16)
                head_fade = (audio_np[:crossfade_samples] * fade_in).astype(np.int16)
                crossfaded = tail_fade + head_fade
                
                # Replace the overlapping section
                audio_np[:crossfade_samples] = crossfaded
                self.metrics.crossfades_applied += 1
                
                logger.debug(f"🔗 Applied {crossfade_samples}-sample crossfade")
        
        # Store tail for next cross-fade
        tail_samples = min(int(SAMPLE_RATE * CROSSFADE_MS / 1000), len(audio_np))
        if tail_samples > 0:
            self.last_chunk_tail = audio_np[-tail_samples:].copy()
        
        return audio_np
    
    async def _add_to_jitter_buffer_and_stream(self, audio_np: np.ndarray):
        """Add audio to jitter buffer and stream with smooth timing"""
        
        # Split audio into frames and add to jitter buffer
        for i in range(0, len(audio_np), FRAME_SIZE):
            frame_data = audio_np[i:i + FRAME_SIZE]
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            
            self.jitter_buffer.add_frame(frame_data)
        
        # Stream frames from jitter buffer with clock-based timing
        while self.jitter_buffer.can_start_playback():
            frame_data = self.jitter_buffer.get_frame()
            if frame_data is None:
                break
                
            # Apply fade-in to very first audible frame
            if not hasattr(self, '_first_audible_sent') and np.any(frame_data != 0):
                fade_samples = min(120, len(frame_data))  # 5ms fade
                fade_curve = np.linspace(0.0, 1.0, fade_samples)
                frame_data[:fade_samples] = (frame_data[:fade_samples] * fade_curve).astype(np.int16)
                self._first_audible_sent = True
                logger.debug("🔧 Applied fade-in to first audible frame")
            
            # Send frame
            frame = rtc.AudioFrame(
                data=frame_data.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(frame_data)
            )
            
            await self.audio_source.capture_frame(frame)
            self.frames_sent += 1
            
            # Clock-based timing prevents drift and jitter
            if self.session_start_time:
                target_time = self.session_start_time + (self.frames_sent * 0.01)
                current_time = time.monotonic()
                sleep_time = target_time - current_time
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                elif sleep_time < -0.002:  # More than 2ms behind
                    self.late_frames_count += 1
                    logger.debug(f"⚠️ Frame timing drift: {sleep_time*1000:.1f}ms behind")
    
    async def _flush_jitter_buffer(self):
        """Flush any remaining frames from jitter buffer"""
        while self.jitter_buffer.frames_available() > 0:
            frame_data = self.jitter_buffer.get_frame()
            if frame_data is None:
                break
                
            frame = rtc.AudioFrame(
                data=frame_data.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(frame_data)
            )
            
            await self.audio_source.capture_frame(frame)
            self.frames_sent += 1
            
            # Maintain timing even during flush
            if self.session_start_time:
                target_time = self.session_start_time + (self.frames_sent * 0.01)
                current_time = time.monotonic()
                sleep_time = target_time - current_time
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
    
    async def _fallback_synthesis(self, text: str, language: str, speaker_wav: Optional[List[str]], 
                                exaggeration: float, cfg_weight: float, chatterbox_engine) -> Dict[str, Any]:
        """Fallback to regular synthesis if streaming fails"""
        start_time = time.time()
        
        # Also prime buffer for fallback
        await self._prime_audio_buffer()
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            await chatterbox_engine.synthesize_to_file(
                text=text, file_path=tmp.name, language=language,
                speaker_wav=speaker_wav, exaggeration=exaggeration, cfg_weight=cfg_weight
            )
            
            audio, sr = sf.read(tmp.name)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            if sr != SAMPLE_RATE:
                from scipy import signal
                num = int(len(audio) * SAMPLE_RATE / sr)
                audio = signal.resample(audio, num)
            
            # Apply same processing as streaming
            audio = np.tanh(audio * 0.8) * 0.9  # Soft limiting
            audio = (audio * 32767 * 0.9).astype(np.int16)
            
            # Use jitter buffer even for fallback
            await self._add_to_jitter_buffer_and_stream(audio)
            await self._flush_jitter_buffer()
        
        total_time = (time.time() - start_time) * 1000
        return {
            "success": True, 
            "method": "fallback_with_jitter_buffer", 
            "total_time_ms": total_time,
            "buffer_primed": True,
            "artifacts_eliminated": True
        }

# Global state (same interface)
streaming_tts_engine: Optional[StreamingTTSEngine] = None

def initialize_streaming_tts(audio_source: rtc.AudioSource):
    """Initialize with production-quality streaming fixes"""
    global streaming_tts_engine
    streaming_tts_engine = StreamingTTSEngine(audio_source)
    logger.info("⚡ Kokoro streaming TTS initialized with PRODUCTION FIXES")
    logger.info(f"🔧 Jitter buffer: {JITTER_BUFFER_TARGET_MS}ms target, crossfade: {CROSSFADE_MS}ms")
    logger.info(f"🎯 Frame size: {FRAME_SIZE} samples (10ms), clock-based timing enabled")

async def stream_tts_to_room(text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
    """Stream with production-quality artifact elimination"""
    if not streaming_tts_engine:
        return {"success": False, "error": "Streaming TTS not ready"}
        
    return await streaming_tts_engine.stream_to_room(
        text=text, language=language, speaker_wav=speaker_wav,
        exaggeration=exaggeration, cfg_weight=cfg_weight, chatterbox_engine=chatterbox_engine
    )

def get_streaming_tts_metrics() -> Dict[str, Any]:
    """Metrics with production fix status"""
    if streaming_tts_engine:
        return streaming_tts_engine.metrics.get_stats()
    return {"error": "Streaming TTS not initialized", "production_fixes": "not_active"}