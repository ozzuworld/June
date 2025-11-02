#!/usr/bin/env python3
"""
Streaming TTS Module - Direct Streaming (Server-side Jitter Buffer Removed)
Keeps cross-fade and precise 10ms clock pacing. Defers jitter buffering to client/LiveKit.
"""
import logging
import asyncio
import time
import tempfile
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import numpy as np
import soundfile as sf
from livekit import rtc
import torch

logger = logging.getLogger("streaming-tts")
logger.setLevel(logging.INFO)

STREAMING_TTS_ENABLED = True
SAMPLE_RATE = 24000
FRAME_SIZE = 240  # 10ms
CROSSFADE_MS = 10

@dataclass
class TTSStreamingMetrics:
    def __init__(self):
        self.first_audio_times = []
        self.streaming_requests = 0
        self.sub_100ms_count = 0
        self.frames_emitted = 0
        self.crossfades_applied = 0
        
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
            "frames_emitted": self.frames_emitted,
            "server_jitter_buffer": "disabled (client-side only)",
        }

class StreamingTTSEngine:
    def __init__(self, audio_source: rtc.AudioSource):
        self.audio_source = audio_source
        self.metrics = TTSStreamingMetrics()
        self.last_chunk_tail = None
        self.session_start_time = None
        self.frames_sent = 0
        self._first_audible_sent = False
        
    async def _prime_audio_buffer(self):
        """Small priming to open LiveKit pipeline (no buffering)."""
        priming_ms = 50
        priming_samples = int(SAMPLE_RATE * priming_ms / 1000)
        silence_buffer = np.zeros(priming_samples, dtype=np.int16)
        logger.info(f"🔧 Priming (server, no jitter): {priming_ms}ms")
        self.session_start_time = time.monotonic()
        for i in range(0, len(silence_buffer), FRAME_SIZE):
            frame_data = silence_buffer[i:i + FRAME_SIZE]
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            await self._emit_frame(frame_data)
        logger.info("✅ Priming complete")
        
    async def stream_to_room(self, text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
        start_time = time.time()
        self.metrics.streaming_requests += 1
        await self._prime_audio_buffer()
        self.last_chunk_tail = None
        self._first_audible_sent = False
        chunks_processed = 0
        
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
                # Directly emit frames as they arrive (no server-side jitter buffer)
                for i in range(0, len(audio_np), FRAME_SIZE):
                    frame_data = audio_np[i:i + FRAME_SIZE]
                    if len(frame_data) < FRAME_SIZE:
                        frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
                    # First audible frame fade-in
                    if not self._first_audible_sent and np.any(frame_data != 0):
                        fade_samples = min(120, len(frame_data))
                        fade_curve = np.linspace(0.0, 1.0, fade_samples)
                        frame_data[:fade_samples] = (frame_data[:fade_samples] * fade_curve).astype(np.int16)
                        self._first_audible_sent = True
                    await self._emit_frame(frame_data)
                    self.metrics.frames_emitted += 1
                chunks_processed += 1
            total_time = (time.time() - start_time) * 1000
            logger.info(f"📊 Stream done: emitted={self.metrics.frames_emitted}, chunks={chunks_processed}")
            return {
                "success": True,
                "method": "kokoro_streaming_direct",
                "chunks_sent": chunks_processed,
                "first_audio_ms": first_audio_time or 0,
                "total_time_ms": round(total_time, 1),
                "server_jitter": "disabled",
            }
        except Exception as e:
            logger.error(f"Kokoro streaming error: {e}")
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)

    async def _emit_frame(self, frame_data: np.ndarray):
        frame = rtc.AudioFrame(
            data=frame_data.tobytes(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            samples_per_channel=len(frame_data)
        )
        await self.audio_source.capture_frame(frame)
        # Precise 10ms clock pacing
        if self.session_start_time is None:
            self.session_start_time = time.monotonic()
            self.frames_sent = 0
        self.frames_sent += 1
        target_time = self.session_start_time + (self.frames_sent * 0.01)
        sleep_time = target_time - time.monotonic()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        if self.frames_sent % 50 == 0:
            logger.info(f"🎚️ Emitted frames: {self.frames_sent}")

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
            for i in range(0, len(audio), FRAME_SIZE):
                frame_data = audio[i:i + FRAME_SIZE]
                if len(frame_data) < FRAME_SIZE:
                    frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
                await self._emit_frame(frame_data)
                self.metrics.frames_emitted += 1
        total_time = (time.time() - start_time) * 1000
        return {"success": True, "method": "fallback_direct", "total_time_ms": total_time}

# Global state (same interface)
streaming_tts_engine: Optional[StreamingTTSEngine] = None

def initialize_streaming_tts(audio_source: rtc.AudioSource):
    global streaming_tts_engine
    streaming_tts_engine = StreamingTTSEngine(audio_source)
    logger.info("⚡ Kokoro streaming TTS initialized: server-side jitter buffer DISABLED (client-side only)")
    logger.info(f"🎯 Frame size: {FRAME_SIZE} samples (10ms), clock-based timing + cross-fade enabled")

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
    return {"error": "Streaming TTS not initialized"}
