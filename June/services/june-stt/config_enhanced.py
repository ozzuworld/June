#!/usr/bin/env python3
"""
Enhanced Configuration for June STT Service with Silero VAD
Combines faster-whisper optimizations with intelligent speech detection
"""
import os
from typing import Optional

class EnhancedConfig:
    """Enhanced STT Service Configuration with Silero VAD"""
    
    # Server Configuration
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Whisper Model Configuration (enhanced from faster-whisper-server)
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")  # auto, cuda, cpu
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Whisper Performance Configuration
    WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    
    # Enhanced Processing Options (from faster-whisper-server)
    USE_BATCHED_INFERENCE: bool = os.getenv("USE_BATCHED_INFERENCE", "true").lower() == "true"
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "8"))
    
    # Dynamic Model Loading (faster-whisper-server feature)
    DYNAMIC_MODEL_LOADING: bool = os.getenv("DYNAMIC_MODEL_LOADING", "true").lower() == "true"
    MODEL_UNLOAD_TIMEOUT: int = int(os.getenv("MODEL_UNLOAD_TIMEOUT", "300"))  # 5 minutes
    
    # Silero VAD Configuration (Intelligent Speech Detection)
    SILERO_VAD_ENABLED: bool = os.getenv("SILERO_VAD_ENABLED", "true").lower() == "true"
    SILERO_VAD_THRESHOLD: float = float(os.getenv("SILERO_VAD_THRESHOLD", "0.5"))  # 0.1-0.9
    SILERO_MIN_SPEECH_MS: int = int(os.getenv("SILERO_MIN_SPEECH_MS", "100"))  # Min speech duration
    SILERO_MIN_SILENCE_MS: int = int(os.getenv("SILERO_MIN_SILENCE_MS", "100"))  # Min silence duration
    
    # Legacy VAD (fallback only)
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "false").lower() == "true"
    
    # Transcription Quality Settings
    CONDITION_ON_PREVIOUS_TEXT: bool = os.getenv("CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
    TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
    LANGUAGE: Optional[str] = os.getenv("WHISPER_LANGUAGE", None)  # Set to "en" for English-only
    
    # File Processing
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    UPLOAD_TIMEOUT: int = int(os.getenv("UPLOAD_TIMEOUT", "30"))
    
    # OpenAI API Compatibility
    OPENAI_API_COMPATIBLE: bool = os.getenv("OPENAI_API_COMPATIBLE", "true").lower() == "true"
    STREAMING_ENABLED: bool = os.getenv("STREAMING_ENABLED", "true").lower() == "true"
    
    # LiveKit Configuration (Real-time Voice Chat)
    LIVEKIT_ENABLED: bool = os.getenv("LIVEKIT_ENABLED", "true").lower() == "true"
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        "ws://livekit-livekit-server:80"
    )
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv(
        "LIVEKIT_API_SECRET", 
        "secret"
    )
    LIVEKIT_ROOM_NAME: str = os.getenv("LIVEKIT_ROOM_NAME", "ozzu-main")
    
    # Simplified Utterance Processing (Silero VAD handles complexity)
    UTTERANCE_PROCESSING: bool = os.getenv("UTTERANCE_PROCESSING", "true").lower() == "true"
    MIN_UTTERANCE_SEC: float = float(os.getenv("MIN_UTTERANCE_SEC", "0.5"))  # Reduced - Silero is smarter
    MAX_UTTERANCE_SEC: float = float(os.getenv("MAX_UTTERANCE_SEC", "8.0"))  # Increased for longer speech
    SILENCE_TIMEOUT_SEC: float = float(os.getenv("SILENCE_TIMEOUT_SEC", "1.0"))  # Simplified
    
    # Anti-feedback Configuration
    EXCLUDE_PARTICIPANTS: set = {
        "june-tts", "june-stt", "tts", "stt", 
        *os.getenv("EXCLUDE_PARTICIPANTS", "").split(",")
    } - {""}  # Remove empty strings
    
    # Orchestrator Integration
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    ORCHESTRATOR_API_KEY: str = os.getenv("ORCHESTRATOR_API_KEY", "")
    ORCHESTRATOR_ENABLED: bool = os.getenv("ORCHESTRATOR_ENABLED", "true").lower() == "true"
    STT_SERVICE_TOKEN: str = os.getenv("STT_SERVICE_TOKEN", "")
    
    # Authentication (Keycloak)
    KEYCLOAK_URL: str = os.getenv("KEYCLOAK_URL", "")
    KEYCLOAK_REALM: str = os.getenv("KEYCLOAK_REALM", "june-realm")
    KEYCLOAK_CLIENT_ID: str = os.getenv("KEYCLOAK_CLIENT_ID", "june-stt")
    KEYCLOAK_ENABLED: bool = os.getenv("KEYCLOAK_ENABLED", "false").lower() == "true"
    
    # Resource Management
    MEMORY_LIMIT_GB: int = int(os.getenv("MEMORY_LIMIT_GB", "8"))
    GPU_MEMORY_FRACTION: float = float(os.getenv("GPU_MEMORY_FRACTION", "0.9"))
    
    # Monitoring and Observability
    METRICS_ENABLED: bool = os.getenv("METRICS_ENABLED", "true").lower() == "true"
    HEALTH_CHECK_INTERVAL: int = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))
    
    @property
    def is_gpu_available(self) -> bool:
        """Check if GPU is available and configured"""
        return self.WHISPER_DEVICE in ["auto", "cuda"]
    
    @property
    def model_cache_path(self) -> str:
        """Get model cache path"""
        return os.path.join(self.WHISPER_CACHE_DIR, self.WHISPER_MODEL.replace("/", "_"))
    
    def validate_configuration(self):
        """Validate configuration settings"""
        errors = []
        
        if self.LIVEKIT_ENABLED and not self.LIVEKIT_API_KEY:
            errors.append("LIVEKIT_API_KEY is required when LiveKit is enabled")
            
        if self.ORCHESTRATOR_ENABLED and not self.ORCHESTRATOR_URL:
            errors.append("ORCHESTRATOR_URL is required when orchestrator is enabled")
            
        if self.USE_BATCHED_INFERENCE and self.BATCH_SIZE < 1:
            errors.append("BATCH_SIZE must be >= 1 when batched inference is enabled")
            
        if self.MIN_UTTERANCE_SEC >= self.MAX_UTTERANCE_SEC:
            errors.append("MIN_UTTERANCE_SEC must be less than MAX_UTTERANCE_SEC")
            
        # Silero VAD validation
        if self.SILERO_VAD_ENABLED:
            if not (0.1 <= self.SILERO_VAD_THRESHOLD <= 0.9):
                errors.append("SILERO_VAD_THRESHOLD must be between 0.1 and 0.9")
            if self.SILERO_MIN_SPEECH_MS < 50:
                errors.append("SILERO_MIN_SPEECH_MS should be at least 50ms")
            
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
    
    def log_configuration(self):
        """Log current configuration (excluding secrets)"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔧 June STT Enhanced Configuration:")
        logger.info(f"   Whisper Model: {self.WHISPER_MODEL} on {self.WHISPER_DEVICE}")
        logger.info(f"   Batched Inference: {self.USE_BATCHED_INFERENCE} (batch_size={self.BATCH_SIZE})")
        logger.info(f"   Silero VAD: {self.SILERO_VAD_ENABLED} (threshold={self.SILERO_VAD_THRESHOLD})")
        logger.info(f"   LiveKit Enabled: {self.LIVEKIT_ENABLED}")
        logger.info(f"   OpenAI API Compatible: {self.OPENAI_API_COMPATIBLE}")
        logger.info(f"   Utterance Limits: {self.MIN_UTTERANCE_SEC}s - {self.MAX_UTTERANCE_SEC}s")
        logger.info(f"   Orchestrator: {self.ORCHESTRATOR_ENABLED}")
        logger.info(f"   Dynamic Model Loading: {self.DYNAMIC_MODEL_LOADING}")

# Global configuration instance
config = EnhancedConfig()

# Validate configuration on import
config.validate_configuration()
