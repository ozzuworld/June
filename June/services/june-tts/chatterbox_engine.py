#!/usr/bin/env python3
"""
Kokoro TTS Engine (PyTorch KPipeline)
Drop-in replacement keeping the same class and method names used by the service.
Removes brittle ONNX downloads and uses kokoro.KPipeline for fast, stable inference.
"""
import asyncio
import logging
import time
from typing import Optional, List, Union

import numpy as np
import soundfile as sf

try:
    from kokoro import KPipeline
except Exception as e:
    raise RuntimeError(f"Failed to import kokoro KPipeline: {e}")

logger = logging.getLogger("chatterbox-engine")


class ChatterboxEngine:
    def __init__(self, device: str = None):
        # device is managed internally by torch; KPipeline handles CUDA if available
        self.device = device
        self.pipeline: Optional[KPipeline] = None
        self.sample_rate = 24000
        self.ready = False

    async def initialize(self):
        """Initialize Kokoro KPipeline (no hardcoded model URLs)."""
        logger.info("🚀 Initializing Kokoro KPipeline (PyTorch)")
        try:
            # 'a' = American English voice set (upstream convention)
            # KPipeline will download/cache required weights automatically via HF
            self.pipeline = KPipeline(lang_code='a')
            self.ready = True
            # Warmup
            await self._warmup()
            logger.info("✅ Kokoro KPipeline ready")
        except Exception as e:
            logger.error(f"Kokoro initialization failed: {e}")
            raise

    async def _warmup(self):
        if not self.ready:
            return
        text = "Kokoro warmup."
        start = time.time()
        # Generate a short snippet and discard
        gen = self.pipeline(text, voice='af_heart', speed=1.0)
        audio_chunks = []
        for _, __, audio in gen:
            audio_chunks.append(audio)
            if sum(len(c) for c in audio_chunks) > self.sample_rate * 0.2:  # ~200ms
                break
        elapsed = (time.time() - start) * 1000
        logger.info(f"⚡ Kokoro warmup time: {elapsed:.0f}ms")

    def is_ready(self) -> bool:
        return bool(self.pipeline) and self.ready

    async def synthesize_to_file(
        self,
        text: str,
        file_path: str,
        language: str = "en",
        speaker_wav: Optional[Union[str, List[str]]] = None,
        speed: float = 1.0,
        exaggeration: float = 0.6,
        cfg_weight: float = 0.8,
        voice_preset: str = None,
        **kwargs
    ) -> str:
        """Generate speech to WAV. Keeps the same signature used by callers."""
        if not self.is_ready():
            raise RuntimeError("Kokoro engine not initialized")
        start = time.time()

        # Simple voice mapping: prefer explicit preset, else default female preset
        voice = voice_preset or 'af_heart'

        # Generate audio with KPipeline (returns generator of chunks)
        gen = self.pipeline(text, voice=voice, speed=speed)
        chunks = [audio for _, __, audio in gen]
        if not chunks:
            raise RuntimeError("Kokoro generated no audio")
        audio = np.concatenate(chunks)

        # Save as 24 kHz mono
        sf.write(file_path, audio, self.sample_rate)

        synth_ms = (time.time() - start) * 1000
        if synth_ms < 100:
            logger.info(f"✅ 🏆 KOKORO SUB-100MS: {synth_ms:.0f}ms")
        else:
            logger.info(f"🎵 Kokoro synthesis: {synth_ms:.0f}ms for {len(text)} chars")
        return file_path

    async def synthesize_streaming(
        self,
        text: str,
        language: str = "en",
        speaker_wav: Optional[List[str]] = None,
        voice_preset: str = None,
        speed: float = 1.0,
        **kwargs
    ):
        """Yield audio chunks for streaming; caller will frame and send to LiveKit."""
        if not self.is_ready():
            raise RuntimeError("Kokoro engine not initialized")
        voice = voice_preset or 'af_heart'
        gen = self.pipeline(text, voice=voice, speed=speed)
        for _, __, audio in gen:
            # audio is float32 numpy in [-1,1]; caller can convert to int16 per frame
            yield audio


# Singleton for main service
chatterbox_engine = ChatterboxEngine()
