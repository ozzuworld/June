#!/usr/bin/env python3
"""
Chatterbox TTS Engine Wrapper - Segfault Fix
Drop-in replacement for XTTS-v2 engine for June with torch.compile disabled
FIXED: Disabled torch.compile optimizations to prevent segmentation faults causing audio breakup
"""
import asyncio
import logging
from typing import Optional, List, Union

import torch
import torchaudio as ta

try:
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
except Exception as e:
    raise RuntimeError(f"Failed to import Chatterbox TTS: {e}")

logger = logging.getLogger("chatterbox-engine")


class ChatterboxEngine:
    def __init__(self, device: str = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model: Optional[ChatterboxTTS] = None
        self.multilingual_model: Optional[ChatterboxMultilingualTTS] = None
        self.sample_rate = 24000
        self.optimized = False

    async def initialize(self):
        logger.info("🚀 Loading Chatterbox TTS models on %s...", self.device)
        # English model
        self.model = await asyncio.to_thread(
            ChatterboxTTS.from_pretrained, device=self.device
        )
        # Multilingual model
        self.multilingual_model = await asyncio.to_thread(
            ChatterboxMultilingualTTS.from_pretrained, device=self.device
        )
        
        # Apply basic optimizations (torch.compile disabled)
        await self._apply_optimizations()
        
        logger.info("✅ Chatterbox TTS models loaded")
    
    async def _apply_optimizations(self):
        """Apply optimizations - torch.compile DISABLED to prevent segfaults"""
        # CRITICAL FIX: Disable torch.compile to prevent segmentation faults
        # that were causing TTS process crashes and audio breakup
        logger.info("⚠️ Skipping torch.compile optimizations to prevent segmentation faults")
        logger.info("ℹ️ This fixes the audio breakup issue caused by TTS process crashes")
        self.optimized = False
        
        # Original torch.compile code disabled:
        # The segfaults were occurring in torch.compile(self.model.t3, mode="reduce-overhead")
        # This was causing the TTS service to crash mid-synthesis, leading to broken audio
        
        # Alternative lightweight optimizations
        if self.device == "cuda":
            try:
                # Enable basic CUDA optimizations that are more stable
                torch.backends.cudnn.benchmark = True
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                logger.info("✅ Applied stable CUDA optimizations (no torch.compile)")
            except Exception as e:
                logger.warning(f"⚠️ CUDA optimization failed: {e}")
        
        logger.info("🔧 Chatterbox engine ready with stable configuration")

    def is_ready(self) -> bool:
        return self.model is not None and self.multilingual_model is not None

    async def synthesize_to_file(
        self,
        text: str,
        file_path: str,
        language: str = "en",
        speaker_wav: Optional[Union[str, List[str]]] = None,
        speed: float = 1.0,  # kept for compatibility, not used directly
        exaggeration: float = 0.6,
        cfg_weight: float = 0.8,
    ) -> str:
        """
        Synthesize text to WAV written at file_path.
        Mirrors XTTS interface used by June.
        """
        wav = await self._generate(text, language, speaker_wav, exaggeration, cfg_weight)
        # Ensure tensor shape: [channels, samples]
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)
        await asyncio.to_thread(ta.save, file_path, wav, self.sample_rate)
        return file_path

    async def _generate(
        self,
        text: str,
        language: str,
        speaker_wav: Optional[Union[str, List[str]]],
        exaggeration: float,
        cfg_weight: float,
    ):
        kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
        if speaker_wav:
            ref = speaker_wav[0] if isinstance(speaker_wav, list) else speaker_wav
            kwargs["audio_prompt_path"] = ref

        if language and language.lower() != "en":
            kwargs["language_id"] = language
            wav = await asyncio.to_thread(self.multilingual_model.generate, text, **kwargs)
        else:
            wav = await asyncio.to_thread(self.model.generate, text, **kwargs)
        return wav


# Singleton used by main service
chatterbox_engine = ChatterboxEngine()