#!/usr/bin/env python3
"""
CosyVoice2 TTS Service Configuration
Simple, clean configuration for CosyVoice2 integration
"""

import os
import torch
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CosyVoice2Config:
    """CosyVoice2 model configuration"""
    # Model settings
    model_dir: str = "/app/pretrained_models"
    model_name: str = "CosyVoice2-0.5B"
    
    # Performance settings
    device: str = "auto"  # auto, cuda, cpu
    load_jit: bool = False  # JIT compilation (slower startup)
    load_trt: bool = False  # TensorRT acceleration
    load_vllm: bool = False  # vLLM acceleration
    fp16: bool = True  # FP16 for faster inference on GPU
    
    # Audio settings
    sample_rate: int = 22050  # CosyVoice2 native sample rate
    streaming: bool = True  # Enable streaming mode
    
    @property
    def model_path(self) -> str:
        return os.path.join(self.model_dir, self.model_name)


@dataclass
class ServiceConfig:
    """Service-level configuration"""
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Service info
    name: str = "june-tts"
    version: str = "1.0.0"
    
    # Logging
    log_level: str = "INFO"
    
    # CORS
    cors_origins: List[str] = None
    
    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = ["*"]


@dataclass
class LiveKitConfig:
    """LiveKit integration configuration"""
    ws_url: str = "wss://livekit.ozzu.world"
    api_key: str = ""
    api_secret: str = ""
    default_room: str = "ozzu-main"
    
    # Connection settings
    connection_timeout: int = 10
    reconnect_attempts: int = 3


class Config:
    """Main configuration class"""
    
    def __init__(self):
        self.cosyvoice = CosyVoice2Config()
        self.service = ServiceConfig()
        self.livekit = LiveKitConfig()
        
        self._load_from_env()
        self._auto_detect_device()
    
    def _load_from_env(self):
        """Load configuration from environment variables"""
        
        # CosyVoice settings
        self.cosyvoice.model_dir = os.getenv("MODEL_DIR", self.cosyvoice.model_dir)
        self.cosyvoice.model_name = os.getenv("COSYVOICE_MODEL", self.cosyvoice.model_name)
        self.cosyvoice.device = os.getenv("TTS_DEVICE", self.cosyvoice.device)
        self.cosyvoice.fp16 = os.getenv("TTS_FP16", "true").lower() == "true"
        self.cosyvoice.streaming = os.getenv("TTS_STREAMING", "true").lower() == "true"
        
        # Service settings
        self.service.host = os.getenv("SERVICE_HOST", self.service.host)
        self.service.port = int(os.getenv("SERVICE_PORT", self.service.port))
        self.service.log_level = os.getenv("LOG_LEVEL", self.service.log_level)
        
        # LiveKit settings
        self.livekit.ws_url = os.getenv("LIVEKIT_WS_URL", self.livekit.ws_url)
        self.livekit.api_key = os.getenv("LIVEKIT_API_KEY", self.livekit.api_key)
        self.livekit.api_secret = os.getenv("LIVEKIT_API_SECRET", self.livekit.api_secret)
        self.livekit.default_room = os.getenv("LIVEKIT_DEFAULT_ROOM", self.livekit.default_room)
        
        # CORS
        cors_env = os.getenv("CORS_ORIGINS")
        if cors_env:
            self.service.cors_origins = [origin.strip() for origin in cors_env.split(",")]
    
    def _auto_detect_device(self):
        """Auto-detect CUDA device"""
        if self.cosyvoice.device == "auto":
            self.cosyvoice.device = "cuda" if torch.cuda.is_available() else "cpu"
    
    def __str__(self) -> str:
        return f"""CosyVoice2 TTS Service Configuration:
  Model: {self.cosyvoice.model_name}
  Device: {self.cosyvoice.device}
  FP16: {self.cosyvoice.fp16}
  Streaming: {self.cosyvoice.streaming}
  Sample Rate: {self.cosyvoice.sample_rate}Hz
  LiveKit: {self.livekit.ws_url}
  Service: {self.service.host}:{self.service.port}"""


# Global configuration instance
config = Config()