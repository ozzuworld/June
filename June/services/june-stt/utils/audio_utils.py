"""Audio processing utilities for June STT"""
import numpy as np
from scipy import signal
from livekit import rtc
import logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

def frame_to_float32_mono(frame: rtc.AudioFrame):
    """Convert audio frame to float32 mono format"""
    sr = frame.sample_rate
    ch = frame.num_channels
    buf = memoryview(frame.data)
    
    try:
        arr = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        arr = np.frombuffer(buf, dtype=np.float32)
    
    if ch and ch > 1:
        try:
            arr = arr.reshape(-1, ch).mean(axis=1)
        except Exception:
            frames = arr[: (len(arr) // ch) * ch]
            arr = frames.reshape(-1, ch).mean(axis=1)
    
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return arr, sr


def resample_to_16k_mono(pcm: np.ndarray, sr: int) -> np.ndarray:
    """Resample audio to 16kHz mono"""
    if sr == SAMPLE_RATE:
        return pcm
    
    gcd = np.gcd(sr, SAMPLE_RATE)
    up = SAMPLE_RATE // gcd
    down = sr // gcd
    out = signal.resample_poly(pcm, up, down).astype(np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def validate_audio_frame(frame: rtc.AudioFrame) -> bool:
    """Validate audio frame for processing"""
    try:
        return (
            frame is not None and
            hasattr(frame, 'data') and
            hasattr(frame, 'sample_rate') and
            len(frame.data) > 0
        )
    except Exception as e:
        logger.debug(f"Audio frame validation failed: {e}")
        return False
