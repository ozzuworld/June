#!/usr/bin/env python3
"""
Streaming TTS Module - Fixed Audio Scrambling Issues
Synchronized frame sizes and improved buffer initialization to prevent audio artifacts
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

STREAMING_TTS_ENABLED = True
SAMPLE_RATE = 24000
# FIXED: Synchronized with main service frame size
FRAME_SIZE = 240  # 10ms frames - matches main service for consistent audio
BUFFER_PRIMING_MS = 100  # Longer priming to prevent artifacts

@dataclass
class TTSStreamingMetrics:
    def __init__(self):
        self.first_audio_times = []
        self.total_chunks = 0
        self.streaming_requests = 0
        self.sub_100ms_count = 0
        
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
            "scrambling_fix": "active"
        }

class StreamingTTSEngine:
    def __init__(self, audio_source: rtc.AudioSource):
        self.audio_source = audio_source
        self.metrics = TTSStreamingMetrics()
        self.buffer_initialized = False
        
    async def _prime_audio_buffer(self):
        """Prime audio buffer to prevent scrambled first chunk"""
        if self.buffer_initialized:
            return
            
        # Send buffer priming silence to initialize LiveKit audio pipeline
        priming_samples = int(SAMPLE_RATE * BUFFER_PRIMING_MS / 1000)
        silence_buffer = np.zeros(priming_samples, dtype=np.int16)
        
        logger.info(f"🔧 Priming audio buffer: {BUFFER_PRIMING_MS}ms ({priming_samples} samples)")
        
        # Send priming frames with consistent timing
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
            # FIXED: Use consistent 10ms timing
            await asyncio.sleep(0.01)  # 10ms timing matches frame size
        
        self.buffer_initialized = True
        logger.info("✅ Audio buffer primed successfully")
        
    async def stream_to_room(self, text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
        start_time = time.time()
        self.metrics.streaming_requests += 1
        
        # FIXED: Always prime buffer before streaming
        await self._prime_audio_buffer()
        
        try:
            # Use Kokoro's native streaming
            chunks_sent = 0
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
                
                # FIXED: Proper audio processing to prevent scrambling
                audio_np = await self._process_audio_chunk(audio_chunk)
                await self._publish_audio_chunk_synchronized(audio_np)
                chunks_sent += 1
            
            total_time = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "method": "kokoro_streaming_fixed",
                "chunks_sent": chunks_sent,
                "first_audio_ms": first_audio_time or 0,
                "total_time_ms": round(total_time, 1),
                "buffer_primed": self.buffer_initialized,
                "scrambling_fix": "applied"
            }
            
        except Exception as e:
            logger.error(f"Kokoro streaming error: {e}")
            # Fallback to regular synthesis
            return await self._fallback_synthesis(text, language, speaker_wav, exaggeration, cfg_weight, chatterbox_engine)
    
    async def _process_audio_chunk(self, audio_chunk) -> np.ndarray:
        """Process audio chunk to prevent scrambling artifacts"""
        # Ensure numpy int16 for LiveKit frames
        if isinstance(audio_chunk, torch.Tensor):
            audio_np = audio_chunk.detach().cpu().numpy()
        else:
            audio_np = audio_chunk
        
        # Convert to mono if needed
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)
        
        # FIXED: Proper audio normalization to prevent clipping/distortion
        # Normalize to prevent scrambling from overflow
        if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
            # Apply gentle compression to prevent sudden jumps
            audio_np = np.tanh(audio_np * 0.8) * 0.9  # Soft limiting
            audio_np = np.clip(audio_np, -1.0, 1.0)
            audio_np = (audio_np * 32767 * 0.9).astype(np.int16)  # Leave headroom
        else:
            # Already int16, ensure proper range
            audio_np = np.clip(audio_np, -32767, 32767).astype(np.int16)
        
        return audio_np
    
    async def _publish_audio_chunk_synchronized(self, audio_np: np.ndarray):
        """Publish audio chunk with synchronized frame timing to prevent scrambling"""
        
        # FIXED: Add small fade-in to first chunk to prevent click/pop
        if not hasattr(self, '_first_chunk_sent'):
            fade_samples = min(480, len(audio_np))  # 20ms fade
            fade_curve = np.linspace(0.0, 1.0, fade_samples)
            audio_np[:fade_samples] = (audio_np[:fade_samples] * fade_curve).astype(np.int16)
            self._first_chunk_sent = True
            logger.info("🔧 Applied fade-in to prevent initial click/pop")
        
        # Send synchronized frames
        for i in range(0, len(audio_np), FRAME_SIZE):
            frame_data = audio_np[i:i + FRAME_SIZE]
            
            if len(frame_data) < FRAME_SIZE:
                frame_data = np.pad(frame_data, (0, FRAME_SIZE - len(frame_data)))
            
            frame = rtc.AudioFrame(
                data=frame_data.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(frame_data)
            )
            
            await self.audio_source.capture_frame(frame)
            # FIXED: Consistent 10ms timing prevents timing artifacts
            await asyncio.sleep(0.01)  # 10ms = FRAME_SIZE / SAMPLE_RATE
    
    async def _publish_raw_audio_chunk(self, audio_np: np.ndarray):
        """Legacy method - redirects to synchronized version"""
        return await self._publish_audio_chunk_synchronized(audio_np)
    
    async def _fallback_synthesis(self, text: str, language: str, speaker_wav: Optional[List[str]], 
                                exaggeration: float, cfg_weight: float, chatterbox_engine) -> Dict[str, Any]:
        """Fallback to regular synthesis if streaming fails"""
        start_time = time.time()
        
        # FIXED: Also prime buffer for fallback
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
            
            # FIXED: Apply same audio processing as streaming
            audio = np.tanh(audio * 0.8) * 0.9  # Soft limiting
            audio = (audio * 32767 * 0.9).astype(np.int16)
            
            await self._publish_audio_chunk_synchronized(audio)
        
        total_time = (time.time() - start_time) * 1000
        return {
            "success": True, 
            "method": "fallback_fixed", 
            "total_time_ms": total_time,
            "buffer_primed": True,
            "scrambling_fix": "applied"
        }

# Global state (same interface)
streaming_tts_engine: Optional[StreamingTTSEngine] = None

def initialize_streaming_tts(audio_source: rtc.AudioSource):
    """Initialize with scrambling fixes applied"""
    global streaming_tts_engine
    streaming_tts_engine = StreamingTTSEngine(audio_source)
    logger.info("⚡ Kokoro streaming TTS initialized with SCRAMBLING FIXES")
    logger.info(f"🔧 Frame size: {FRAME_SIZE} samples (10ms), Buffer priming: {BUFFER_PRIMING_MS}ms")

async def stream_tts_to_room(text: str, language: str = "en", speaker_wav: Optional[List[str]] = None,
                           exaggeration: float = 0.6, cfg_weight: float = 0.8, chatterbox_engine = None) -> Dict[str, Any]:
    """Stream with audio scrambling fixes applied"""
    if not streaming_tts_engine:
        return {"success": False, "error": "Streaming TTS not ready"}
        
    return await streaming_tts_engine.stream_to_room(
        text=text, language=language, speaker_wav=speaker_wav,
        exaggeration=exaggeration, cfg_weight=cfg_weight, chatterbox_engine=chatterbox_engine
    )

def get_streaming_tts_metrics() -> Dict[str, Any]:
    """Metrics with scrambling fix status"""
    if streaming_tts_engine:
        return streaming_tts_engine.metrics.get_stats()
    return {"error": "Streaming TTS not initialized", "scrambling_fix": "not_active"}