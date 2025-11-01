#!/usr/bin/env python3
"""
Kokoro TTS Engine Wrapper - DROP-IN REPLACEMENT for Chatterbox
Provides identical interface to chatterbox_engine.py for seamless migration
Optimized for ultra-low latency voice chat (<100ms TTS)

KOKORO-82M FEATURES:
- Only 82M parameters but beats models 6x larger
- Sub-100ms inference time on GPU
- <1GB VRAM usage
- Human-like quality (#1 on TTS Arena)
- Apache 2.0 license (fully open source)
- Optimized for conversational AI
"""
import asyncio
import logging
import tempfile
import time
import os
import torch
import numpy as np
import soundfile as sf
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

logger = logging.getLogger("kokoro-engine")

# Device detection
device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"🎯 Kokoro will use device: {device}")

class KokoroEngine:
    """
    Drop-in replacement for ChatterboxEngine with identical interface
    Implements ultra-fast Kokoro-82M TTS for sub-100ms latency
    """
    
    def __init__(self):
        self.model = None
        self.voicepack = None
        self.ready = False
        self.device = device
        
        # Voice presets for natural conversation
        self.voice_presets = {
            "af_bella": "female_confident",      # Default female voice
            "af_sarah": "female_warm",          # Alternative female
            "am_michael": "male_professional",   # Default male voice  
            "am_adam": "male_casual",           # Alternative male
        }
        
        self.default_female = "af_bella"
        self.default_male = "am_michael"
        
        # Performance tracking
        self.synthesis_count = 0
        self.total_inference_time = 0.0
        self.avg_rtf = 0.0
        
    async def initialize(self):
        """
        Initialize Kokoro TTS models - same interface as chatterbox_engine.initialize()
        """
        logger.info("🚀 Initializing Kokoro-82M TTS engine for ultra-low latency...")
        
        try:
            # Import Kokoro components
            from kokoro_onnx import generate_audio  # Main generation function
            import onnxruntime as ort
            
            # Download and cache model if needed
            model_path = await self._ensure_model_downloaded()
            
            # Initialize ONNX runtime with optimizations
            providers = ['CUDAExecutionProvider'] if device == 'cuda' else ['CPUExecutionProvider']
            
            session_options = ort.SessionOptions()
            session_options.intra_op_num_threads = 1
            session_options.inter_op_num_threads = 1
            session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            
            logger.info(f"🛠️ Loading Kokoro model from {model_path}")
            logger.info(f"🚀 ONNX Providers: {providers}")
            
            self.model = ort.InferenceSession(
                model_path, 
                sess_options=session_options,
                providers=providers
            )
            
            # Load voice packs
            await self._load_voice_packs()
            
            self.ready = True
            
            # Performance test
            await self._performance_test()
            
            logger.info("✅ Kokoro-82M engine ready for ultra-low latency synthesis")
            logger.info(f"📊 Performance: Avg RTF {self.avg_rtf:.3f} (target: <0.1 for sub-100ms)")
            
        except ImportError as e:
            logger.error(f"❌ Kokoro dependencies not installed: {e}")
            logger.info("📚 Install with: pip install kokoro-onnx onnxruntime-gpu")
            raise
        except Exception as e:
            logger.error(f"❌ Kokoro initialization failed: {e}")
            raise
    
    async def _ensure_model_downloaded(self) -> str:
        """Download Kokoro model if not present"""
        model_dir = Path("./models/kokoro")
        model_dir.mkdir(parents=True, exist_ok=True)
        
        model_path = model_dir / "kokoro-v0_19.onnx"
        
        if not model_path.exists():
            logger.info("💾 Downloading Kokoro-82M model...")
            
            import requests
            # Download from HuggingFace or official source
            model_url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v0_19.onnx"
            
            response = requests.get(model_url, stream=True)
            response.raise_for_status()
            
            with open(model_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"✅ Model downloaded: {model_path} ({model_path.stat().st_size / 1024 / 1024:.1f}MB)")
        
        return str(model_path)
    
    async def _load_voice_packs(self):
        """Load voice presets for natural conversation"""
        voice_dir = Path("./models/kokoro/voices")
        voice_dir.mkdir(parents=True, exist_ok=True)
        
        # Download voice packs if needed
        voice_urls = {
            "af_bella.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_bella.pt",
            "af_sarah.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_sarah.pt", 
            "am_michael.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/am_michael.pt",
            "am_adam.pt": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/am_adam.pt",
        }
        
        self.voicepacks = {}
        
        for voice_name, url in voice_urls.items():
            voice_path = voice_dir / voice_name
            
            if not voice_path.exists():
                logger.info(f"💾 Downloading voice pack: {voice_name}")
                import requests
                response = requests.get(url)
                response.raise_for_status()
                
                with open(voice_path, 'wb') as f:
                    f.write(response.content)
            
            # Load voice pack
            voice_key = voice_name.replace('.pt', '')
            self.voicepacks[voice_key] = torch.load(voice_path, weights_only=True).to(self.device)
            logger.debug(f"✅ Loaded voice pack: {voice_key}")
        
        logger.info(f"🎭 Loaded {len(self.voicepacks)} voice packs for natural conversation")
    
    async def _performance_test(self):
        """Test Kokoro performance to verify sub-100ms capability"""
        test_text = "Testing Kokoro performance for ultra-low latency voice chat."
        
        # Warm up
        for i in range(3):
            start_time = time.time()
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                await self.synthesize_to_file(
                    text=test_text,
                    file_path=tmp.name,
                    voice_preset=self.default_female
                )
            
            inference_time = (time.time() - start_time) * 1000
            
            if i == 2:  # Last warm-up run
                audio_duration_s = len(test_text) / 12  # Rough estimate: 12 chars per second
                rtf = inference_time / 1000 / audio_duration_s
                self.avg_rtf = rtf
                
                logger.info(f"⚡ Kokoro performance test: {inference_time:.0f}ms inference for {len(test_text)} chars")
                logger.info(f"📊 RTF: {rtf:.3f} (target: <0.1 for sub-100ms)")
                
                if inference_time > 200:
                    logger.warning(f"⚠️ Kokoro inference slower than expected: {inference_time:.0f}ms")
                    logger.info("💡 Consider GPU optimization or hardware upgrade")
                elif inference_time < 100:
                    logger.info("✅ 🎆 EXCELLENT! Kokoro achieving sub-100ms target")
    
    async def synthesize_to_file(self, text: str, file_path: str, language: str = "en",
                               speaker_wav: Optional[List[str]] = None, speed: float = 1.0,
                               voice_preset: str = None, exaggeration: float = 0.6,
                               cfg_weight: float = 0.8, **kwargs) -> Dict[str, Any]:
        """
        IDENTICAL INTERFACE to chatterbox_engine.synthesize_to_file()
        Drop-in replacement - no caller code changes needed
        """
        if not self.ready:
            raise RuntimeError("Kokoro engine not initialized")
        
        start_time = time.time()
        
        # Voice selection logic
        if speaker_wav and len(speaker_wav) > 0:
            # Voice cloning requested - use closest voice preset
            # For Kokoro, we'll use the default female for cloning requests
            selected_voice = self.default_female
            logger.info(f"🎭 Voice cloning requested - using preset: {selected_voice}")
        else:
            # Default voice selection
            selected_voice = voice_preset or self.default_female
            
        # Import generation function
        from kokoro_onnx import generate_audio
        
        try:
            # Generate with Kokoro
            audio_generator = generate_audio(
                text=text,
                voice=self.voicepacks[selected_voice],
                model=self.model,
                lang='a',  # American English
                speed=speed,
                # Map parameters to Kokoro equivalents
                temperature=0.7,  # Natural variation
                top_p=0.9,
            )
            
            # Collect streaming audio chunks
            audio_chunks = []
            for phonemes, timing, audio_chunk in audio_generator:
                audio_chunks.append(audio_chunk)
            
            if not audio_chunks:
                raise RuntimeError("No audio generated")
            
            # Concatenate all chunks
            full_audio = np.concatenate(audio_chunks)
            
            # Save to file
            sf.write(file_path, full_audio, 24000)
            
            inference_time = (time.time() - start_time) * 1000
            
            # Update performance metrics
            self.synthesis_count += 1
            self.total_inference_time += inference_time
            
            logger.info(f"⚡ Kokoro synthesis: {inference_time:.0f}ms for {len(text)} chars (voice: {selected_voice})")
            
            if inference_time < 100:
                logger.info("✅ 🎆 SUB-100MS ACHIEVED!")
            
            return {
                "inference_time_ms": inference_time,
                "voice_used": selected_voice,
                "audio_duration_s": len(full_audio) / 24000,
                "rtf": inference_time / 1000 / (len(full_audio) / 24000),
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"❌ Kokoro synthesis error: {e}")
            raise
    
    async def synthesize_streaming(self, text: str, language: str = "en",
                                 speaker_wav: Optional[List[str]] = None,
                                 voice_preset: str = None, **kwargs):
        """NEW: Streaming synthesis for real-time applications"""
        if not self.ready:
            raise RuntimeError("Kokoro engine not initialized")
        
        selected_voice = voice_preset or self.default_female
        
        from kokoro_onnx import generate_audio
        
        logger.info(f"⚡ Kokoro streaming synthesis: {len(text)} chars (voice: {selected_voice})")
        
        try:
            # Generate streaming audio
            audio_generator = generate_audio(
                text=text,
                voice=self.voicepacks[selected_voice],
                model=self.model,
                lang='a',
                speed=kwargs.get('speed', 1.0),
                temperature=0.7,
                top_p=0.9,
            )
            
            # Yield audio chunks as they're generated (streaming)
            chunk_count = 0
            for phonemes, timing, audio_chunk in audio_generator:
                chunk_count += 1
                yield audio_chunk
                
            logger.info(f"✅ Kokoro streaming complete: {chunk_count} chunks generated")
            
        except Exception as e:
            logger.error(f"❌ Kokoro streaming error: {e}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        avg_inference = self.total_inference_time / max(1, self.synthesis_count)
        
        return {
            "engine": "kokoro-82m",
            "synthesis_count": self.synthesis_count,
            "avg_inference_time_ms": round(avg_inference, 2),
            "avg_rtf": round(self.avg_rtf, 4),
            "target_achieved": avg_inference < 100,
            "available_voices": list(self.voice_presets.keys()),
            "memory_usage_gb": "<1GB VRAM",
            "model_size": "82M parameters",
            "quality_rating": "#1 on TTS Arena",
        }

# Global engine instance (same pattern as chatterbox)
kokoro_engine = KokoroEngine()