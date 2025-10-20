"""Configuration with enhanced AI and session settings"""
import os
from typing import List
from pydantic import BaseModel


class ServiceConfig(BaseModel):
    """Service URLs"""
    tts_base_url: str
    stt_base_url: str
    gemini_api_key: str = ""
    stt_service_token: str = ""  # For webhook authentication


class LiveKitConfig(BaseModel):
    """LiveKit configuration"""
    api_key: str
    api_secret: str
    ws_url: str


class SessionConfig(BaseModel):
    """Session management configuration"""
    max_history_messages: int = 20  # Keep recent N messages
    session_timeout_hours: int = 24  # Auto-cleanup after N hours
    cleanup_interval_minutes: int = 60  # Run cleanup every N minutes
    max_context_tokens: int = 8000  # Max tokens for context


class AIConfig(BaseModel):
    """AI service configuration"""
    model: str = "gemini-2.0-flash-exp"
    temperature: float = 0.7
    max_output_tokens: int = 200  # Keep responses short for voice
    max_input_length: int = 1000  # Character limit for user input
    enable_summarization: bool = True  # Auto-summarize long conversations
    voice_response_mode: bool = True  # Optimize for voice (brief responses)


class RateLimitConfig(BaseModel):
    """Rate limiting configuration"""
    enabled: bool = True
    max_requests_per_minute: int = 60
    max_requests_per_hour: int = 1000
    max_tokens_per_day: int = 100000


class AppConfig:
    """Main configuration"""
    
    def __init__(self):
        self.port = int(os.getenv("PORT", "8080"))
        self.host = os.getenv("HOST", "0.0.0.0")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # CORS
        cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
        self.cors_origins = [o.strip() for o in cors_origins.split(",")]
        
        # Service configuration
        self.services = self._load_service_config()
        
        # LiveKit configuration
        self.livekit = self._load_livekit_config()
        
        # Session configuration
        self.sessions = self._load_session_config()
        
        # AI configuration
        self.ai = self._load_ai_config()
        
        # Rate limiting
        self.rate_limit = self._load_rate_limit_config()
    
    def _load_service_config(self) -> ServiceConfig:
        return ServiceConfig(
            tts_base_url=os.getenv(
                "TTS_SERVICE_URL",
                "http://june-tts:8000"
            ),
            stt_base_url=os.getenv(
                "STT_SERVICE_URL",
                "http://june-stt:8080"
            ),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            stt_service_token=os.getenv("STT_SERVICE_TOKEN", "")
        )
    
    def _load_livekit_config(self) -> LiveKitConfig:
        return LiveKitConfig(
            api_key=os.getenv(
                "LIVEKIT_API_KEY",
                "devkey"
            ),
            api_secret=os.getenv(
                "LIVEKIT_API_SECRET",
                "secret"
            ),
            ws_url=os.getenv(
                "LIVEKIT_WS_URL",
                "ws://livekit-livekit-server:80"
            )
        )
    
    def _load_session_config(self) -> SessionConfig:
        return SessionConfig(
            max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "20")),
            session_timeout_hours=int(os.getenv("SESSION_TIMEOUT_HOURS", "24")),
            cleanup_interval_minutes=int(os.getenv("CLEANUP_INTERVAL_MINUTES", "60")),
            max_context_tokens=int(os.getenv("MAX_CONTEXT_TOKENS", "8000"))
        )
    
    def _load_ai_config(self) -> AIConfig:
        return AIConfig(
            model=os.getenv("AI_MODEL", "gemini-2.0-flash-exp"),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.7")),
            max_output_tokens=int(os.getenv("AI_MAX_OUTPUT_TOKENS", "200")),
            max_input_length=int(os.getenv("AI_MAX_INPUT_LENGTH", "1000")),
            enable_summarization=os.getenv("AI_ENABLE_SUMMARIZATION", "true").lower() == "true",
            voice_response_mode=os.getenv("AI_VOICE_MODE", "true").lower() == "true"
        )
    
    def _load_rate_limit_config(self) -> RateLimitConfig:
        return RateLimitConfig(
            enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true",
            max_requests_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
            max_requests_per_hour=int(os.getenv("RATE_LIMIT_PER_HOUR", "1000")),
            max_tokens_per_day=int(os.getenv("RATE_LIMIT_TOKENS_PER_DAY", "100000"))
        )


config = AppConfig()