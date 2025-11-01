#!/usr/bin/env python3
"""
Streaming TTS Module - Chunked audio generation for LiveKit
Enables sub-second time-to-first-audio by streaming TTS chunks
"""
import logging
import asyncio
import time
import tempfile
from typing import AsyncIterator, Dict, Any, Optional, List
from dataclasses import dataclass

import torch
import numpy as np
import soundfile as sf
from livekit import rtc

logger = logging.getLogger("streaming-tts")

# Feature flags
STREAMING_TTS_ENABLED = config.get("TTS_STREAMING_ENABLED", True) if 'config' in globals() else True
CHUNK_SIZE_MS = 200  # Generate 200ms audio chunks
SAMPLE_RATE = 24000


@dataclass
class TTSStreamingMetrics:
    """Track streaming TTS performance"""
    first_audio_times: List[float]
    chunk_generation_times: List[float]
    total_chunks: int
    streaming_requests: int
    
    def __post_init__(self):
        if not hasattr(self, 'first_audio_times'):
            self.first_audio_times = []
        if not hasattr(self, 'chunk_generation_times'):
            self.chunk_generation_times = []
        if not hasattr(self, 'total_chunks'):
            self.total_chunks = 0
        if not hasattr(self, 'streaming_requests'):
            self.streaming_requests = 0
            
    def record_first_audio(self, time_ms: float):
        self.first_audio_times.append(time_ms)
        
    def record_chunk_generation(self, time_ms: float):
        self.chunk_generation_times.append(time_ms)
        self.total_chunks += 1
        
    def record_streaming_request(self):
        self.streaming_requests += 1
        
    def get_stats(self) -> Dict[str, Any]:
        avg_first_audio = sum(self.first_audio_times) / len(self.first_audio_times) if self.first_audio_times else 0
        avg_chunk_time = sum(self.chunk_generation_times) / len(self.chunk_generation_times) if self.chunk_generation_times else 0
        
        return {
            "avg_first_audio_ms": round(avg_first_audio, 1),
            "avg_chunk_generation_ms": round(avg_chunk_time, 1),
            "total_chunks_generated": self.total_chunks,
            "streaming_requests": self.streaming_requests
        }


class StreamingTTSEngine:
    """Manages streaming TTS generation and LiveKit publishing"""
    
    def __init__(self, audio_source: rtc.AudioSource):
        self.audio_source = audio_source
        self.metrics = TTSStreamingMetrics([], [], 0, 0)
        self.chunk_samples = int((CHUNK_SIZE_MS / 1000) * SAMPLE_RATE)
        
    async def stream_to_room(
        self,
        text: str,
        language: str = "en",
        speaker_wav: Optional[List[str]] = None,
        exaggeration: float = 0.6,
        cfg_weight: float = 0.8,
        chatterbox_engine = None
    ) -> Dict[str, Any]:
        """Stream TTS generation directly to LiveKit room"""
        if not STREAMING_TTS_ENABLED:
            # Fallback to regular synthesis
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)
            
        start_time = time.time()
        self.metrics.record_streaming_request()
        
        try:
            # Check if model supports streaming
            if hasattr(chatterbox_engine, 'stream_synthesize_to_chunks'):
                # Native streaming support
                first_chunk = True
                chunks_sent = 0
                
                async for audio_chunk in chatterbox_engine.stream_synthesize_to_chunks(
                    text=text,
                    language=language,
                    speaker_wav=speaker_wav,
                    exaggeration=exaggeration,
                    cfg_weight=cfg_weight,
                    chunk_size_ms=CHUNK_SIZE_MS
                ):
                    chunk_start = time.time()
                    
                    # Record first audio latency
                    if first_chunk:
                        first_audio_time = (chunk_start - start_time) * 1000
                        self.metrics.record_first_audio(first_audio_time)
                        logger.info(f"🎵 First audio chunk in {first_audio_time:.0f}ms")
                        first_chunk = False
                        
                    # Stream chunk to LiveKit
                    await self._publish_audio_chunk(audio_chunk)
                    chunks_sent += 1
                    
                    chunk_time = (time.time() - chunk_start) * 1000
                    self.metrics.record_chunk_generation(chunk_time)
                    
                total_time = (time.time() - start_time) * 1000
                logger.info(f"✅ Streaming TTS completed: {chunks_sent} chunks in {total_time:.0f}ms")
                
                return {
                    "success": True,
                    "method": "streaming",
                    "chunks_sent": chunks_sent,
                    "total_time_ms": round(total_time, 1),
                    "first_audio_ms": round(self.metrics.first_audio_times[-1], 1) if self.metrics.first_audio_times else 0
                }
                
            else:
                # Fallback: synthesize full audio and chunk for streaming effect
                logger.debug("⚠️ Using fallback chunked streaming (no native support)")
                return await self._chunked_fallback(
                    text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine, start_time
                )
                
        except Exception as e:
            logger.error(f"❌ Streaming TTS error: {e}")
            # Emergency fallback
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)
    
    async def _chunked_fallback(
        self,
        text: str,
        language: str,
        speaker_wav: Optional[List[str]],
        exaggeration: float,
        cfg_weight: float,
        chatterbox_engine,
        start_time: float
    ) -> Dict[str, Any]:
        """Generate full audio and stream in chunks"""
        try:
            # Generate complete audio
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                out_path = f.name
                
            await chatterbox_engine.synthesize_to_file(
                text=text,
                file_path=out_path,
                language=language,
                speaker_wav=speaker_wav,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight
            )
            
            # Load and chunk audio for streaming
            audio, sr = sf.read(out_path)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            if sr != SAMPLE_RATE:
                from scipy import signal
                num = int(len(audio) * SAMPLE_RATE / sr)
                audio = signal.resample(audio, num)
                
            audio = (audio * 32767).astype(np.int16)
            
            # Stream in chunks
            chunks_sent = 0
            for i in range(0, len(audio), self.chunk_samples):
                chunk = audio[i:i + self.chunk_samples]
                if len(chunk) > 0:
                    if chunks_sent == 0:
                        # Record first audio time
                        first_audio_time = (time.time() - start_time) * 1000
                        self.metrics.record_first_audio(first_audio_time)
                        logger.info(f"🎵 First audio chunk (fallback) in {first_audio_time:.0f}ms")
                        
                    await self._publish_raw_audio_chunk(chunk)
                    chunks_sent += 1
                    
                    # Small delay to prevent overwhelming
                    await asyncio.sleep(CHUNK_SIZE_MS / 1000)
            
            total_time = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "method": "chunked_fallback",
                "chunks_sent": chunks_sent,
                "total_time_ms": round(total_time, 1),
                "first_audio_ms": round(self.metrics.first_audio_times[-1], 1) if self.metrics.first_audio_times else 0
            }
            
        finally:
            import os
            if 'out_path' in locals() and os.path.exists(out_path):
                os.unlink(out_path)
    
    async def _fallback_synthesis(self, text: str, language: str, speaker_wav: Optional[List[str]], exaggeration: float, cfg_weight: float, chatterbox_engine) -> Dict[str, Any]:
        """Complete fallback to regular synthesis"""
        logger.info("ℹ️ Using regular (non-streaming) TTS synthesis")
        
        start_time = time.time()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
            
        try:
            await chatterbox_engine.synthesize_to_file(
                text=text,
                file_path=out_path,
                language=language,
                speaker_wav=speaker_wav,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight
            )
            
            with open(out_path, "rb") as f:
                audio_data = f.read()
                
            # Publish complete audio
            from main import publish_audio_to_room
            result = await publish_audio_to_room(audio_data)
            
            total_time = (time.time() - start_time) * 1000
            result.update({
                "method": "fallback",
                "total_time_ms": round(total_time, 1)
            })
            
            return result
            
        finally:
            import os
            if os.path.exists(out_path):
                os.unlink(out_path)
    
    async def _publish_audio_chunk(self, audio_chunk: torch.Tensor):
        """Publish audio chunk to LiveKit (tensor format)"""
        try:
            # Convert tensor to int16 numpy array
            if isinstance(audio_chunk, torch.Tensor):
                audio_np = audio_chunk.detach().cpu().numpy()
                if audio_np.ndim > 1:
                    audio_np = audio_np.mean(axis=0)  # Convert to mono
                audio_np = (audio_np * 32767).astype(np.int16)
            else:
                audio_np = audio_chunk
                
            await self._publish_raw_audio_chunk(audio_np)
            
        except Exception as e:
            logger.error(f"❌ Error publishing audio chunk: {e}")
    
    async def _publish_raw_audio_chunk(self, audio_np: np.ndarray):
        """Publish raw numpy audio chunk to LiveKit"""
        try:
            # Ensure proper chunk size
            if len(audio_np) == 0:
                return
                
            # Pad if necessary for frame alignment
            frame_samples = 480  # 20ms frames at 24kHz
            if len(audio_np) < frame_samples:
                audio_np = np.pad(audio_np, (0, frame_samples - len(audio_np)))
            
            # Create and send frame
            frame = rtc.AudioFrame(
                data=audio_np.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(audio_np)
            )
            
            await self.audio_source.capture_frame(frame)
            
        except Exception as e:
            logger.error(f"❌ Error publishing raw audio chunk: {e}")


# Global streaming TTS engine (initialized by main.py)
streaming_tts_engine: Optional[StreamingTTSEngine] = None


def initialize_streaming_tts(audio_source: rtc.AudioSource):
    """Initialize streaming TTS engine with LiveKit audio source"""
    global streaming_tts_engine
    streaming_tts_engine = StreamingTTSEngine(audio_source)
    logger.info("⚡ Streaming TTS engine initialized")


async def stream_tts_to_room(
    text: str,
    language: str = "en",
    speaker_wav: Optional[List[str]] = None,
    exaggeration: float = 0.6,
    cfg_weight: float = 0.8,
    chatterbox_engine = None
) -> Dict[str, Any]:
    """Public interface for streaming TTS to room"""
    if not streaming_tts_engine:
        logger.error("❌ Streaming TTS engine not initialized")
        return {"success": False, "error": "Streaming TTS not ready"}
        
    return await streaming_tts_engine.stream_to_room(
        text=text,
        language=language,
        speaker_wav=speaker_wav,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        chatterbox_engine=chatterbox_engine
    )


def get_streaming_tts_metrics() -> Dict[str, Any]:
    """Get streaming TTS performance metrics"""
    if streaming_tts_engine:
        return streaming_tts_engine.metrics.get_stats()
    return {"error": "Streaming TTS not initialized"}