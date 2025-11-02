#!/usr/bin/env python3
"""
Streaming TTS Module - Production-Quality Audio Streaming
Fix: Jitter buffer playback logic and enhanced debugging to trace audio flow
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
logger.setLevel(logging.INFO)

STREAMING_TTS_ENABLED = True
SAMPLE_RATE = 24000
FRAME_SIZE = 240  # 10ms
JITTER_BUFFER_TARGET_MS = 20  # 2 frames
JITTER_BUFFER_MAX_MS = 30     # 3 frames
CROSSFADE_MS = 10
ADAPTIVE_JITTER = False

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
        self.frames_emitted = 0
        self.frames_buffered = 0
        self.frames_dropped = 0
        self.stalls = 0
        
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
            "frame_size": FRAME_SIZE,
            "jitter_target_ms": JITTER_BUFFER_TARGET_MS,
            "buffer_underruns": self.buffer_underruns,
            "crossfades_applied": self.crossfades_applied,
            "jitter_adjustments": self.jitter_buffer_adjustments,
            "frames_emitted": self.frames_emitted,
            "frames_buffered": self.frames_buffered,
            "frames_dropped": self.frames_dropped,
            "stalls": self.stalls
        }

class JitterBuffer:
    """Small output buffer to smooth audio delivery and prevent artifacts"""
    
    def __init__(self, target_frames: int = 2, max_frames: int = 3):
        self.target_frames = target_frames
        self.max_frames = max_frames
        self.buffer = deque()
        self.started_playback = False
        self.underruns = 0
        self.dropped = 0
        
    def add_frame(self, frame_data: np.ndarray):
        if len(self.buffer) >= self.max_frames:
            self.buffer.popleft()
            self.dropped += 1
        self.buffer.append(frame_data.copy())
        
    def ready_to_start(self) -> bool:
        return len(self.buffer) >= self.target_frames
        
    def get_frame(self) -> Optional[np.ndarray]:
        # Once playback started, allow emitting if any frame exists
        if self.started_playback:
            if len(self.buffer) == 0:
                self.underruns += 1
                return None
            return self.buffer.popleft()
        # Before start, require target_frames
        if len(self.buffer) >= self.target_frames:
            self.started_playback = True
            return self.buffer.popleft()
        return None
        
    def frames_available(self) -> int:
        return len(self.buffer)

class StreamingTTSEngine:
    def __init__(self, audio_source: rtc.AudioSource):
        self.audio_source = audio_source
        self.metrics = TTSStreamingMetrics()
        self.buffer_initialized = False
        self.jitter_buffer = JitterBuffer()
        self.last_chunk_tail = None
        self.session_start_time = None
        self.frames_sent = 0
        self.late_frames_count = 0
        self._first_audible_sent = False
        
    async def _prime_audio_buffer(self):
        if self.buffer_initialized:
            return
        priming_ms = 100
        priming_samples = int(SAMPLE_RATE * priming_ms / 1000)
        silence_buffer = np.zeros(priming_samples, dtype=np.int16)
        logger.info(f"🔧 Priming audio buffer: {priming_ms}ms ({priming_samples} samples)")
        self.session_start_time = time.monotonic()
        frame_count = 0
        for i in range(0, len(silence_buffer), FRAME_SIZE):
            frame_data = silence_buffer[i:i + FRAME_SIZE]
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            await self._emit_frame(frame_data)
            frame_count += 1
        self.frames_sent = frame_count
        self.buffer_initialized = True
        logger.info("✅ Audio buffer primed successfully")
        
    async def stream_to_room(self, text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
        start_time = time.time()
        self.metrics.streaming_requests += 1
        await self._prime_audio_buffer()
        self.jitter_buffer = JitterBuffer(target_frames=2, max_frames=3)
        self.last_chunk_tail = None
        self._first_audible_sent = False
        chunks_processed = 0
        stalls = 0
        
        try:
            first_audio_time = None
            async for audio_chunk in chatterbox_engine.synthesize_streaming(
                text=text, language=language, speaker_wav=speaker_wav,
                voice_preset="af_bella", speed=1.0
            ):
                if first_audio_time is None:
                    first_audio_time = (time.time() - start_time) * 1000
                    self.metrics.record_first_audio(first_audio_time)
                    logger.info(f"🎵 First audio: {first_audio_time:.0f}ms")
                audio_np = await self._process_audio_chunk_with_crossfade(audio_chunk)
                buffered = self._buffer_frames(audio_np)
                self.metrics.frames_buffered += buffered
                chunks_processed += 1
                # Drain available frames; never block on target after start
                drained = await self._drain_jitter_buffer()
                if drained == 0:
                    stalls += 1
            # Flush remaining
            await self._drain_jitter_buffer(flush_all=True)
            self.metrics.buffer_underruns += self.jitter_buffer.underruns
            self.metrics.frames_dropped += self.jitter_buffer.dropped
            self.metrics.stalls += stalls
            total_time = (time.time() - start_time) * 1000
            logger.info(f"📊 Stream done: buffered={self.metrics.frames_buffered}, emitted={self.metrics.frames_emitted}, underruns={self.metrics.buffer_underruns}, dropped={self.metrics.frames_dropped}, stalls={self.metrics.stalls}")
            return {
                "success": True,
                "method": "kokoro_streaming_production_fixed",
                "chunks_sent": chunks_processed,
                "first_audio_ms": first_audio_time or 0,
                "total_time_ms": round(total_time, 1),
                "buffer_primed": self.buffer_initialized,
                "jitter_buffer_underruns": self.jitter_buffer.underruns,
                "frames_emitted": self.metrics.frames_emitted,
                "frames_buffered": self.metrics.frames_buffered,
                "frames_dropped": self.metrics.frames_dropped,
            }
        except Exception as e:
            logger.error(f"Kokoro streaming error: {e}")
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)
    
    def _buffer_frames(self, audio_np: np.ndarray) -> int:
        count = 0
        for i in range(0, len(audio_np), FRAME_SIZE):
            frame_data = audio_np[i:i + FRAME_SIZE]
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            self.jitter_buffer.add_frame(frame_data)
            count += 1
        logger.debug(f"🧃 Buffered {count} frames (available={self.jitter_buffer.frames_available()})")
        return count

    async def _drain_jitter_buffer(self, flush_all: bool = False) -> int:
        emitted = 0
        # If playback not started yet, require target; once started, emit if any
        while True:
            frame_data = self.jitter_buffer.get_frame()
            if frame_data is None:
                # If not started and not enough frames, break
                if not self.jitter_buffer.started_playback and not flush_all:
                    break
                # If started and nothing available, stop draining now
                if self.jitter_buffer.started_playback and not flush_all:
                    break
                # If flushing all and empty, break as well
                if flush_all:
                    break
            else:
                # First audible frame fade-in
                if not self._first_audible_sent and np.any(frame_data != 0):
                    fade_samples = min(120, len(frame_data))
                    fade_curve = np.linspace(0.0, 1.0, fade_samples)
                    frame_data[:fade_samples] = (frame_data[:fade_samples] * fade_curve).astype(np.int16)
                    self._first_audible_sent = True
                    logger.debug("🔧 Applied fade-in to first audible frame")
                await self._emit_frame(frame_data)
                emitted += 1
            # If not flushing, emit at most frames currently available to keep CPU low
            if not flush_all and emitted > 0 and self.jitter_buffer.frames_available() == 0:
                break
        self.metrics.frames_emitted += emitted
        return emitted

    async def _emit_frame(self, frame_data: np.ndarray):
        frame = rtc.AudioFrame(
            data=frame_data.tobytes(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            samples_per_channel=len(frame_data)
        )
        await self.audio_source.capture_frame(frame)
        # Clock-based pacing
        if self.session_start_time is None:
            self.session_start_time = time.monotonic()
            self.frames_sent = 0
        self.frames_sent += 1
        target_time = self.session_start_time + (self.frames_sent * 0.01)
        sleep_time = target_time - time.monotonic()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        # Log occasionally
        if self.frames_sent % 50 == 0:
            logger.info(f"🎚️ Emitted frames: {self.frames_sent} (buffer={self.jitter_buffer.frames_available()})")

    async def _process_audio_chunk_with_crossfade(self, audio_chunk) -> np.ndarray:
        if isinstance(audio_chunk, torch.Tensor):
            audio_np = audio_chunk.detach().cpu().numpy()
        else:
            audio_np = audio_chunk
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)
        if audio_np.dtype in [np.float32, np.float64]:
            audio_np = np.tanh(audio_np * 0.8) * 0.9
            audio_np = np.clip(audio_np, -1.0, 1.0)
            audio_np = (audio_np * 32767 * 0.9).astype(np.int16)
        else:
            audio_np = np.clip(audio_np, -32767, 32767).astype(np.int16)
        if self.last_chunk_tail is not None and len(self.last_chunk_tail) > 0:
            crossfade_samples = min(
                int(SAMPLE_RATE * CROSSFADE_MS / 1000),
                len(self.last_chunk_tail),
                len(audio_np)
            )
            if crossfade_samples > 0:
                fade_out = np.linspace(1.0, 0.0, crossfade_samples)
                fade_in = np.linspace(0.0, 1.0, crossfade_samples)
                tail_fade = (self.last_chunk_tail[-crossfade_samples:] * fade_out).astype(np.int16)
                head_fade = (audio_np[:crossfade_samples] * fade_in).astype(np.int16)
                audio_np[:crossfade_samples] = tail_fade + head_fade
                self.metrics.crossfades_applied += 1
        tail_samples = min(int(SAMPLE_RATE * CROSSFADE_MS / 1000), len(audio_np))
        if tail_samples > 0:
            self.last_chunk_tail = audio_np[-tail_samples:].copy()
        return audio_np
    
    async def _fallback_synthesis(self, text: str, language: str, speaker_wav: Optional[List[str]], 
                                exaggeration: float, cfg_weight: float, chatterbox_engine) -> Dict[str, Any]:
        start_time = time.time()
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
            audio = np.tanh(audio * 0.8) * 0.9
            audio = (audio * 32767 * 0.9).astype(np.int16)
            _ = self._buffer_frames(audio)
            await self._drain_jitter_buffer(flush_all=True)
        total_time = (time.time() - start_time) * 1000
        return {"success": True, "method": "fallback_with_20ms_jitter", "total_time_ms": total_time, "buffer_primed": True}

# Global state (same interface)
streaming_tts_engine: Optional[StreamingTTSEngine] = None

def initialize_streaming_tts(audio_source: rtc.AudioSource):
    global streaming_tts_engine
    streaming_tts_engine = StreamingTTSEngine(audio_source)
    logger.info("⚡ Kokoro streaming TTS initialized with 20ms jitter buffer (fixed logic)")
    logger.info(f"🔧 Jitter buffer: {JITTER_BUFFER_TARGET_MS}ms target (2 frames), crossfade: {CROSSFADE_MS}ms")
    logger.info(f"🎯 Frame size: {FRAME_SIZE} samples (10ms), clock-based timing enabled")

async def stream_tts_to_room(text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
    if not streaming_tts_engine:
        return {"success": False, "error": "Streaming TTS not ready"}
    return await streaming_tts_engine.stream_to_room(
        text=text, language=language, speaker_wav=speaker_wav,
        exaggeration=exaggeration, cfg_weight=cfg_weight, chatterbox_engine=chatterbox_engine
    )

def get_streaming_tts_metrics() -> Dict[str, Any]:
    if streaming_tts_engine:
        return streaming_tts_engine.metrics.get_stats()
    return {"error": "Streaming TTS not initialized", "production_fixes": "not_active"}