#!/usr/bin/env python3
"""
June TTS Service Configuration - Chatterbox TTS
Centralized configuration management for Chatterbox TTS service
"""

import os
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class ChatterboxConfig:
    """Chatterbox TTS-specific configuration"""
    # Engine settings
    engine: str = "chatterbox"  # Only Chatterbox TTS
    device: str = "auto"  # auto, cuda, cpu
    model_cache_dir: str = "/app/models"
    
    # Audio settings
    sample_rate: int = 24000
    chunk_duration: float = 0.2  # seconds
    max_text_length: int = 1000
    chunk_size: int = 25  # Tokens per chunk for Chatterbox streaming
    
    # Chatterbox-specific parameters
    default_exaggeration: float = 0.5  # Emotion level (0.0-1.5)
    default_temperature: float = 0.9   # Voice randomness (0.1-1.0)
    default_cfg_weight: float = 0.3    # Guidance weight (0.0-1.0)
    
    # Voice cloning settings
    enable_voice_cloning: bool = True
    voice_reference_max_length: int = 30  # seconds
    
    # Performance settings
    gpu_memory_fraction: float = 0.8
    max_concurrent_requests: int = 4
    enable_streaming: bool = True
    batch_size: int = 1
    
    # Quality settings
    default_speed: float = 1.0

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
    audio_codec: str = "opus"
    
@dataclass
class ServiceConfig:
    """Service-level configuration"""
    # Service identity
    name: str = "june-tts"
    version: str = "2.0.0"
    description: str = "High-performance TTS service with Chatterbox TTS"
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    
    # Security
    enable_auth: bool = True
    cors_origins: List[str] = None
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Health and monitoring
    health_check_interval: int = 30
    metrics_enabled: bool = True
    
    # External services
    orchestrator_url: str = "http://june-orchestrator.june-services.svc.cluster.local:8080"

class Config:
    """Main configuration class for Chatterbox TTS service"""
    
    def __init__(self):
        self.chatterbox = ChatterboxConfig()
        self.livekit = LiveKitConfig()
        self.service = ServiceConfig()
        
        # Load from environment variables
        self._load_from_env()
        
        # Auto-detect device if needed
        if self.chatterbox.device == "auto":
            import torch
            self.chatterbox.device = "cuda" if torch.cuda.is_available() else "cpu"
            
        # Set CORS origins default
        if self.service.cors_origins is None:
            self.service.cors_origins = ["*"]  # Configure for production
    
    def _load_from_env(self):
        """Load configuration from environment variables"""
        
        # Chatterbox TTS settings
        self.chatterbox.engine = os.getenv("TTS_ENGINE", self.chatterbox.engine)
        self.chatterbox.device = os.getenv("TTS_DEVICE", self.chatterbox.device)
        self.chatterbox.sample_rate = int(os.getenv("TTS_SAMPLE_RATE", self.chatterbox.sample_rate))
        self.chatterbox.chunk_size = int(os.getenv("CHATTERBOX_CHUNK_SIZE", self.chatterbox.chunk_size))
        self.chatterbox.default_exaggeration = float(os.getenv(
            "CHATTERBOX_EXAGGERATION", self.chatterbox.default_exaggeration
        ))
        self.chatterbox.default_temperature = float(os.getenv(
            "CHATTERBOX_TEMPERATURE", self.chatterbox.default_temperature
        ))
        self.chatterbox.default_cfg_weight = float(os.getenv(
            "CHATTERBOX_CFG_WEIGHT", self.chatterbox.default_cfg_weight
        ))
        self.chatterbox.max_concurrent_requests = int(os.getenv(
            "TTS_MAX_CONCURRENT", self.chatterbox.max_concurrent_requests
        ))
        
        # LiveKit settings
        self.livekit.ws_url = os.getenv("LIVEKIT_WS_URL", self.livekit.ws_url)
        self.livekit.api_key = os.getenv("LIVEKIT_API_KEY", self.livekit.api_key)
        self.livekit.api_secret = os.getenv("LIVEKIT_API_SECRET", self.livekit.api_secret)
        self.livekit.default_room = os.getenv("LIVEKIT_DEFAULT_ROOM", self.livekit.default_room)
        
        # Service settings
        self.service.host = os.getenv("SERVICE_HOST", self.service.host)
        self.service.port = int(os.getenv("SERVICE_PORT", self.service.port))
        self.service.log_level = os.getenv("LOG_LEVEL", self.service.log_level)
        self.service.enable_auth = os.getenv("ENABLE_AUTH", "true").lower() == "true"
        
        # External services
        self.service.orchestrator_url = os.getenv(
            "ORCHESTRATOR_URL", self.service.orchestrator_url
        )
        
        # CORS origins from environment (comma-separated)
        cors_env = os.getenv("CORS_ORIGINS")
        if cors_env:
            self.service.cors_origins = [origin.strip() for origin in cors_env.split(",")]
    
    def get_chatterbox_config(self) -> dict:
        """Get Chatterbox TTS configuration"""
        return {
            "engine": "chatterbox",
            "device": self.chatterbox.device,
            "sample_rate": self.chatterbox.sample_rate,
            "chunk_size": self.chatterbox.chunk_size,
            "streaming_enabled": self.chatterbox.enable_streaming,
            "voice_cloning_enabled": self.chatterbox.enable_voice_cloning,
            "max_reference_length": self.chatterbox.voice_reference_max_length,
            "parameters": {
                "exaggeration": {
                    "min": 0.0,
                    "max": 1.5,
                    "default": self.chatterbox.default_exaggeration,
                    "description": "Emotion intensity and expressiveness"
                },
                "temperature": {
                    "min": 0.1,
                    "max": 1.0,
                    "default": self.chatterbox.default_temperature,
                    "description": "Voice randomness and variation"
                },
                "cfg_weight": {
                    "min": 0.0,
                    "max": 1.0,
                    "default": self.chatterbox.default_cfg_weight,
                    "description": "Guidance weight for voice control"
                },
                "speed": {
                    "min": 0.5,
                    "max": 2.0,
                    "default": self.chatterbox.default_speed,
                    "description": "Speech speed multiplier"
                }
            },
            "supported_languages": ["en", "es", "fr", "de", "it", "pt", "ru", "zh"],
            "features": [
                "Zero-shot voice cloning",
                "Real-time streaming",
                "Emotion control (exaggeration)",
                "Voice guidance (cfg_weight)",
                "Temperature control",
                "Multi-language support",
                "GPU acceleration"
            ]
        }
    
    def get_performance_config(self) -> dict:
        """Get performance-related configuration"""
        return {
            "device": self.chatterbox.device,
            "max_concurrent_requests": self.chatterbox.max_concurrent_requests,
            "gpu_memory_fraction": self.chatterbox.gpu_memory_fraction,
            "batch_size": self.chatterbox.batch_size,
            "streaming_enabled": self.chatterbox.enable_streaming,
            "chunk_duration": self.chatterbox.chunk_duration,
            "chunk_size": self.chatterbox.chunk_size,
            "sample_rate": self.chatterbox.sample_rate
        }
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        # Validate Chatterbox TTS settings
        if self.chatterbox.sample_rate not in [16000, 22050, 24000, 44100, 48000]:
            issues.append(f"Invalid sample rate: {self.chatterbox.sample_rate}")
            
        if self.chatterbox.chunk_duration <= 0 or self.chatterbox.chunk_duration > 2.0:
            issues.append(f"Invalid chunk duration: {self.chatterbox.chunk_duration}")
            
        if self.chatterbox.chunk_size <= 0 or self.chatterbox.chunk_size > 100:
            issues.append(f"Invalid chunk size: {self.chatterbox.chunk_size}")
            
        if self.chatterbox.max_concurrent_requests <= 0 or self.chatterbox.max_concurrent_requests > 20:
            issues.append(f"Invalid max concurrent requests: {self.chatterbox.max_concurrent_requests}")
        
        # Validate Chatterbox parameters
        if not (0.0 <= self.chatterbox.default_exaggeration <= 1.5):
            issues.append(f"Invalid exaggeration: {self.chatterbox.default_exaggeration}")
            
        if not (0.1 <= self.chatterbox.default_temperature <= 1.0):
            issues.append(f"Invalid temperature: {self.chatterbox.default_temperature}")
            
        if not (0.0 <= self.chatterbox.default_cfg_weight <= 1.0):
            issues.append(f"Invalid cfg_weight: {self.chatterbox.default_cfg_weight}")
        
        # Validate LiveKit settings
        if not self.livekit.ws_url.startswith(("ws://", "wss://")):
            issues.append(f"Invalid LiveKit WebSocket URL: {self.livekit.ws_url}")
        
        # Validate service settings
        if self.service.port <= 0 or self.service.port > 65535:
            issues.append(f"Invalid service port: {self.service.port}")
            
        return issues
    
    def __str__(self) -> str:
        """String representation of configuration"""
        return f"""June TTS Service Configuration (Chatterbox):
  Engine: {self.chatterbox.engine} on {self.chatterbox.device}
  Sample Rate: {self.chatterbox.sample_rate}Hz
  Chunk Size: {self.chatterbox.chunk_size} tokens
  Exaggeration: {self.chatterbox.default_exaggeration}
  Temperature: {self.chatterbox.default_temperature}
  CFG Weight: {self.chatterbox.default_cfg_weight}
  LiveKit: {self.livekit.ws_url}
  Service: {self.service.host}:{self.service.port}
  Auth Enabled: {self.service.enable_auth}
  Streaming: {self.chatterbox.enable_streaming}
  Max Concurrent: {self.chatterbox.max_concurrent_requests}"""

# Global configuration instance
config = Config()