#!/usr/bin/env python3
"""
June TTS Service Configuration
Centralized configuration management for TTS service
"""

import os
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class TTSConfig:
    """TTS-specific configuration"""
    # Engine settings
    engine: str = "kokoro"  # or "chatterbox"
    device: str = "auto"  # auto, cuda, cpu
    model_cache_dir: str = "/app/models"
    
    # Audio settings
    sample_rate: int = 24000
    chunk_duration: float = 0.2  # seconds
    max_text_length: int = 1000
    
    # Voice settings
    default_voice: str = "af_bella"
    enable_voice_cloning: bool = True
    voice_reference_max_length: int = 30  # seconds
    
    # Performance settings
    gpu_memory_fraction: float = 0.8
    max_concurrent_requests: int = 4
    enable_streaming: bool = True
    batch_size: int = 1
    
    # Quality settings
    default_speed: float = 1.0
    default_emotion_level: float = 0.5
    enable_emotion_control: bool = True

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
    description: str = "High-performance TTS service with Chatterbox/Kokoro"
    
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
    orchestrator_url: str = "https://api.ozzu.world"
class Config:
    """Main configuration class"""
    
    def __init__(self):
        self.tts = TTSConfig()
        self.livekit = LiveKitConfig()
        self.service = ServiceConfig()
        
        # Load from environment variables
        self._load_from_env()
        
        # Auto-detect device if needed
        if self.tts.device == "auto":
            import torch
            self.tts.device = "cuda" if torch.cuda.is_available() else "cpu"
            
        # Set CORS origins default
        if self.service.cors_origins is None:
            self.service.cors_origins = ["*"]  # Configure for production
    
    def _load_from_env(self):
        """Load configuration from environment variables"""
        
        # TTS settings
        self.tts.engine = os.getenv("TTS_ENGINE", self.tts.engine)
        self.tts.device = os.getenv("TTS_DEVICE", self.tts.device)
        self.tts.sample_rate = int(os.getenv("TTS_SAMPLE_RATE", self.tts.sample_rate))
        self.tts.default_voice = os.getenv("TTS_DEFAULT_VOICE", self.tts.default_voice)
        self.tts.max_concurrent_requests = int(os.getenv(
            "TTS_MAX_CONCURRENT", self.tts.max_concurrent_requests
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
    
    def get_voices_config(self) -> dict:
        """Get available voices configuration"""
        return {
            "default_voice": self.tts.default_voice,
            "available_voices": {
                "af_bella": {
                    "name": "Bella",
                    "language": "en",
                    "gender": "female",
                    "accent": "american",
                    "description": "Warm, friendly female voice"
                },
                "af_sarah": {
                    "name": "Sarah", 
                    "language": "en",
                    "gender": "female",
                    "accent": "american",
                    "description": "Clear, professional female voice"
                },
                "am_adam": {
                    "name": "Adam",
                    "language": "en", 
                    "gender": "male",
                    "accent": "american",
                    "description": "Deep, authoritative male voice"
                },
                "am_michael": {
                    "name": "Michael",
                    "language": "en",
                    "gender": "male", 
                    "accent": "american",
                    "description": "Friendly, conversational male voice"
                }
            },
            "voice_cloning_enabled": self.tts.enable_voice_cloning,
            "max_reference_length": self.tts.voice_reference_max_length
        }
    
    def get_performance_config(self) -> dict:
        """Get performance-related configuration"""
        return {
            "device": self.tts.device,
            "max_concurrent_requests": self.tts.max_concurrent_requests,
            "gpu_memory_fraction": self.tts.gpu_memory_fraction,
            "batch_size": self.tts.batch_size,
            "streaming_enabled": self.tts.enable_streaming,
            "chunk_duration": self.tts.chunk_duration,
            "sample_rate": self.tts.sample_rate
        }
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        # Validate TTS settings
        if self.tts.sample_rate not in [16000, 22050, 24000, 44100, 48000]:
            issues.append(f"Invalid sample rate: {self.tts.sample_rate}")
            
        if self.tts.chunk_duration <= 0 or self.tts.chunk_duration > 2.0:
            issues.append(f"Invalid chunk duration: {self.tts.chunk_duration}")
            
        if self.tts.max_concurrent_requests <= 0 or self.tts.max_concurrent_requests > 20:
            issues.append(f"Invalid max concurrent requests: {self.tts.max_concurrent_requests}")
        
        # Validate LiveKit settings
        if not self.livekit.ws_url.startswith(("ws://", "wss://")):
            issues.append(f"Invalid LiveKit WebSocket URL: {self.livekit.ws_url}")
        
        # Validate service settings
        if self.service.port <= 0 or self.service.port > 65535:
            issues.append(f"Invalid service port: {self.service.port}")
            
        return issues
    
    def __str__(self) -> str:
        """String representation of configuration"""
        return f"""June TTS Service Configuration:
  Engine: {self.tts.engine} on {self.tts.device}
  Sample Rate: {self.tts.sample_rate}Hz
  Default Voice: {self.tts.default_voice}
  LiveKit: {self.livekit.ws_url}
  Service: {self.service.host}:{self.service.port}
  Auth Enabled: {self.service.enable_auth}
  Streaming: {self.tts.enable_streaming}
  Max Concurrent: {self.tts.max_concurrent_requests}"""

# Global configuration instance
config = Config()