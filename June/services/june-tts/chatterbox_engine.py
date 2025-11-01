#!/usr/bin/env python3
"""
Chatterbox TTS Engine Wrapper - Simple Optimized Version
Drop-in replacement for XTTS-v2 engine for June with basic optimizations
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
        
        # Apply basic optimizations
        await self._apply_optimizations()
        
        logger.info("✅ Chatterbox TTS models loaded")
    
    async def _apply_optimizations(self):
        """Apply torch.compile optimizations if available"""
        if self.device == "cuda":
            try:
                logger.info("⚡ Applying torch.compile optimizations...")
                
                # Check PyTorch version and apply optimizations
                if hasattr(torch, 'compile'):
                    try:
                        # Compile critical components for speed
                        if hasattr(self.model, 't3'):
                            self.model.t3 = torch.compile(self.model.t3, mode="reduce-overhead")
                        if hasattr(self.multilingual_model, 't3'):
                            self.multilingual_model.t3 = torch.compile(self.multilingual_model.t3, mode="reduce-overhead")
                        
                        self.optimized = True
                        logger.info("✅ torch.compile optimizations applied")
                    except Exception as e:
                        logger.warning(f"⚠️ torch.compile failed: {e}")
                        self.optimized = False
                else:
                    logger.warning("⚠️ torch.compile not available")
                    
            except Exception as e:
                logger.warning(f"⚠️ Optimization failed: {e}")
                self.optimized = False
        else:
            logger.info("ℹ️ Skipping optimizations (CPU device)")

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
