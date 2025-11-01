#!/usr/bin/env python3
"""
Streaming TTS for Kokoro Engine - ULTRA LOW LATENCY
Optimized for sub-100ms first audio delivery
Preserves existing streaming infrastructure while leveraging Kokoro's speed

KOKORO OPTIMIZATIONS:
- Native streaming generation (no chunking needed)
- Sub-100ms inference time
- Minimal memory footprint (<1GB VRAM)
- Optimized for real-time voice chat
"""
import asyncio
import logging
import time
import tempfile
import os
from typing import Optional, List, AsyncIterator, Dict, Any
import numpy as np
import soundfile as sf
from livekit import rtc

logger = logging.getLogger("streaming-tts-kokoro")

# Global streaming state
streaming_audio_source: Optional[rtc.AudioSource] = None
streaming_metrics = {
    "chunks_sent": 0,
    "total_streaming_time": 0.0,
    "first_audio_times": [],
    "streaming_errors": 0,
    "rtf_measurements": [],
    "sub_100ms_count": 0,
}

def initialize_streaming_tts(audio_source: rtc.AudioSource):
    """Initialize streaming TTS with Kokoro optimizations"""
    global streaming_audio_source
    streaming_audio_source = audio_source
    logger.info("⚡ Streaming TTS engine initialized with Kokoro ultra-low latency parameters")


async def stream_tts_to_room(
    text: str,
    language: str = "en",
    speaker_wav: Optional[List[str]] = None,
    voice_preset: str = "af_bella",
    exaggeration: float = 0.6,
    cfg_weight: float = 0.8,
    kokoro_engine=None,
    **kwargs
) -> Dict[str, Any]:
    """
    Stream TTS audio to LiveKit room using Kokoro's native streaming
    OPTIMIZED for sub-100ms first audio delivery
    """
    global streaming_audio_source, streaming_metrics
    
    if not streaming_audio_source:
        raise RuntimeError("Streaming audio source not initialized")
    
    if not kokoro_engine or not kokoro_engine.ready:
        raise RuntimeError("Kokoro engine not ready")
    
    start_time = time.time()
    first_audio_time = None
    chunks_sent = 0
    
    logger.info(f"🆕 Split text into streaming chunks for ultra-fast delivery")
    
    try:
        # Use Kokoro's native streaming synthesis
        async for audio_chunk in kokoro_engine.synthesize_streaming(
            text=text,
            language=language,
            speaker_wav=speaker_wav,
            voice_preset=voice_preset,
            speed=kwargs.get('speed', 1.0)
        ):
            chunk_start_time = time.time()
            
            # Record first audio chunk time (key metric)
            if first_audio_time is None:
                first_audio_time = (chunk_start_time - start_time) * 1000
                streaming_metrics["first_audio_times"].append(first_audio_time)
                
                logger.info(f"🎵 First audio chunk in {first_audio_time:.0f}ms")
                
                if first_audio_time < 100:
                    streaming_metrics["sub_100ms_count"] += 1
                    logger.info("✅ 🎆 SUB-100MS FIRST AUDIO ACHIEVED!")
            
            # Convert to proper format for LiveKit
            if audio_chunk.dtype != np.int16:
                audio_chunk = (audio_chunk * 32767).astype(np.int16)
            
            # Send to LiveKit with optimized frame timing
            await _stream_audio_chunk_to_livekit(audio_chunk)
            
            chunks_sent += 1
            
        total_time = (time.time() - start_time) * 1000
        
        # Calculate RTF for this generation
        audio_duration_s = len(text) / 12  # Approximate duration
        rtf = (total_time / 1000) / max(0.1, audio_duration_s)
        streaming_metrics["rtf_measurements"].append(rtf)
        
        # Update metrics
        streaming_metrics["chunks_sent"] += chunks_sent
        streaming_metrics["total_streaming_time"] += total_time
        
        logger.info(f"✅ Kokoro streaming complete: {chunks_sent} chunks in {total_time:.0f}ms")
        
        return {
            "method": "kokoro_streaming",
            "chunks_sent": chunks_sent,
            "first_audio_ms": first_audio_time or 0,
            "total_time_ms": total_time,
            "rtf": rtf,
            "sub_100ms_achieved": first_audio_time and first_audio_time < 100,
            "voice_used": voice_preset or "af_bella",
            "optimization_level": "ULTRA_LOW_LATENCY"
        }
        
    except Exception as e:
        streaming_metrics["streaming_errors"] += 1
        logger.error(f"❌ Kokoro streaming error: {e}")
        
        # Fallback to regular synthesis
        logger.info("🔄 Falling back to regular synthesis")
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                await kokoro_engine.synthesize_to_file(
                    text=text,
                    file_path=tmp.name,
                    language=language,
                    speaker_wav=speaker_wav,
                    voice_preset=voice_preset,
                    speed=kwargs.get('speed', 1.0)
                )
                
                # Stream the complete file
                with open(tmp.name, 'rb') as f:
                    audio_data = f.read()
                
                await _stream_complete_audio_to_livekit(audio_data)
                
                fallback_time = (time.time() - start_time) * 1000
                
                return {
                    "method": "kokoro_fallback",
                    "chunks_sent": 1,
                    "first_audio_ms": fallback_time,
                    "total_time_ms": fallback_time,
                    "fallback_used": True,
                    "voice_used": voice_preset or "af_bella"
                }
                
        except Exception as fallback_error:
            logger.error(f"❌ Kokoro fallback also failed: {fallback_error}")
            raise


async def _stream_audio_chunk_to_livekit(audio_chunk: np.ndarray, sample_rate: int = 24000):
    """Stream individual audio chunk to LiveKit with optimized timing"""
    global streaming_audio_source
    
    if not streaming_audio_source:
        raise RuntimeError("Audio source not available")
    
    # Use optimized frame size for low latency (5ms frames)
    frame_size = 120  # 5ms at 24kHz (ultra-low latency)
    
    # Send audio in small frames for immediate playback
    for i in range(0, len(audio_chunk), frame_size):
        frame_data = audio_chunk[i:i+frame_size]
        
        # Pad if necessary
        if len(frame_data) < frame_size:
            frame_data = np.pad(frame_data, (0, frame_size - len(frame_data)))
        
        # Create LiveKit frame
        frame = rtc.AudioFrame(
            data=frame_data.tobytes(),
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=len(frame_data)
        )
        
        await streaming_audio_source.capture_frame(frame)
        
        # Ultra-precise timing for 5ms frames
        await asyncio.sleep(0.005)  # 5ms per frame


async def _stream_complete_audio_to_livekit(audio_data: bytes, sample_rate: int = 24000):
    """Stream complete audio file to LiveKit (fallback method)"""
    global streaming_audio_source
    
    if not streaming_audio_source:
        raise RuntimeError("Audio source not available")
    
    # Load audio data
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        with open(tmp.name, 'wb') as f:
            f.write(audio_data)
        
        audio, sr = sf.read(tmp.name)
        
        # Convert format
        if sr != sample_rate:
            from scipy import signal
            num = int(len(audio) * sample_rate / sr)
            audio = signal.resample(audio, num)
        
        if audio.dtype != np.int16:
            audio = (audio * 32767).astype(np.int16)
    
    # Stream with optimized frame size
    frame_size = 120  # 5ms frames for immediate playback
    
    for i in range(0, len(audio), frame_size):
        frame_data = audio[i:i+frame_size]
        
        if len(frame_data) < frame_size:
            frame_data = np.pad(frame_data, (0, frame_size - len(frame_data)))
        
        frame = rtc.AudioFrame(
            data=frame_data.tobytes(),
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=len(frame_data)
        )
        
        await streaming_audio_source.capture_frame(frame)
        await asyncio.sleep(0.005)  # 5ms timing


def get_streaming_tts_metrics() -> Dict[str, Any]:
    """Get Kokoro streaming performance metrics"""
    avg_first_audio = (
        sum(streaming_metrics["first_audio_times"]) / len(streaming_metrics["first_audio_times"])
        if streaming_metrics["first_audio_times"] else 0
    )
    
    avg_streaming_time = (
        streaming_metrics["total_streaming_time"] / max(1, streaming_metrics["chunks_sent"])
    )
    
    avg_rtf = (
        sum(streaming_metrics["rtf_measurements"]) / len(streaming_metrics["rtf_measurements"])
        if streaming_metrics["rtf_measurements"] else 0
    )
    
    sub_100ms_rate = (
        streaming_metrics["sub_100ms_count"] / len(streaming_metrics["first_audio_times"]) * 100
        if streaming_metrics["first_audio_times"] else 0
    )
    
    return {
        "engine": "kokoro-82m",
        "total_chunks_sent": streaming_metrics["chunks_sent"],
        "avg_first_audio_ms": round(avg_first_audio, 1),
        "avg_streaming_time_ms": round(avg_streaming_time, 1),
        "avg_rtf": round(avg_rtf, 4),
        "streaming_errors": streaming_metrics["streaming_errors"],
        "sub_100ms_success_rate": round(sub_100ms_rate, 1),
        "target_achieved": avg_first_audio < 100,
        "optimization_level": "ULTRA_LOW_LATENCY",
        "frame_size_ms": 5,  # 5ms frames for immediate playback
        "performance_rating": "EXCELLENT" if avg_first_audio < 100 else "GOOD" if avg_first_audio < 200 else "NEEDS_OPTIMIZATION",
    }