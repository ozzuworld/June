"""Configuration with enhanced AI and session settings"""
import os
import logging
from typing import List
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


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


class RedisConfig(BaseModel):
    """Redis configuration for conversational AI"""
    host: str = "redis.june-services.svc.cluster.local"
    port: int = 6379
    db: int = 1
    password: str = ""
    

class ConversationalAIConfig(BaseModel):
    """Conversational AI configuration"""
    enabled: bool = True
    context_ttl_days: int = 7
    history_ttl_days: int = 30
    summary_ttl_days: int = 90
    max_conversation_length: int = 200  # Max messages per conversation
    topic_extraction_enabled: bool = True
    intent_recognition_enabled: bool = True
    learning_adaptation_enabled: bool = True


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
    max_output_tokens: int = 1000  # Increased for conversational AI
    max_input_length: int = 1000  # Character limit for user input
    enable_summarization: bool = True  # Auto-summarize long conversations
    voice_response_mode: bool = True  # Optimize for voice (brief responses)
    default_speaker: str = "Alexandra Hisakawa"  # Default XTTS V2 speaker for June's voice
    
    @field_validator('default_speaker')
    @classmethod
    def validate_speaker(cls, v):
        # List of valid XTTS V2 speakers for validation
        valid_speakers = {
            "Alexandra Hisakawa", "Claribel Dervla", "Daisy Studious", "Gracie Wise", 
            "Tammie Ema", "Alison Dietlinde", "Ana Florence", "Annmarie Nele", 
            "Asya Anara", "Brenda Stern", "Gitta Nikolina", "Henriette Usha",
            "Sofia Hellen", "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie",
            "Nova Hogarth", "Maja Ruoho", "Uta Obando", "Lidiya Szekeres",
            "Chandra MacFarland", "Szofi Granger", "Camilla Holmström", 
            "Lilya Stainthorpe", "Zofija Kendrick", "Narelle Moon", "Barbora MacLean",
            "Alma María", "Rosemary Okafor", "Andrew Chipper", "Badr Odhiambo",
            "Dionisio Schuyler", "Royston Min", "Viktor Eka", "Abrahan Mack",
            "Adde Michal", "Baldur Sanjin", "Craig Gutsy", "Damien Black",
            "Gilberto Mathias", "Ilkin Urbano", "Kazuhiko Atallah", "Ludvig Milivoj",
            "Suad Qasim", "Torcull Diarmuid", "Viktor Menelaos", "Zacharie Aimilios",
            "Ige Behringer", "Filip Traverse", "Damjan Chapman", "Wulf Carlevaro",
            "Aaron Dreschner", "Kumar Dahl", "Eugenio Mataracı", "Ferran Simen",
            "Xavier Hayasaka", "Luis Moray", "Marcos Rudaski"
        }
        
        if v not in valid_speakers:
            logger.warning(f"Invalid speaker '{v}', falling back to 'Alexandra Hisakawa'")
            return "Alexandra Hisakawa"
        
        return v


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
        
        # Redis configuration
        self.redis = self._load_redis_config()
        
        # Conversational AI configuration
        self.conversational_ai = self._load_conversational_ai_config()
        
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
    
    def _load_redis_config(self) -> RedisConfig:
        return RedisConfig(
            host=os.getenv("REDIS_HOST", "redis.june-services.svc.cluster.local"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "1")),
            password=os.getenv("REDIS_PASSWORD", "")
        )
    
    def _load_conversational_ai_config(self) -> ConversationalAIConfig:
        return ConversationalAIConfig(
            enabled=os.getenv("CONVERSATIONAL_AI_ENABLED", "true").lower() == "true",
            context_ttl_days=int(os.getenv("CONTEXT_TTL_DAYS", "7")),
            history_ttl_days=int(os.getenv("HISTORY_TTL_DAYS", "30")),
            summary_ttl_days=int(os.getenv("SUMMARY_TTL_DAYS", "90"))
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
            max_output_tokens=int(os.getenv("AI_MAX_OUTPUT_TOKENS", "1000")),
            max_input_length=int(os.getenv("AI_MAX_INPUT_LENGTH", "1000")),
            enable_summarization=os.getenv("AI_ENABLE_SUMMARIZATION", "true").lower() == "true",
            voice_response_mode=os.getenv("AI_VOICE_MODE", "true").lower() == "true",
            default_speaker=os.getenv("AI_DEFAULT_SPEAKER", "Alexandra Hisakawa")
        )
    
    def _load_rate_limit_config(self) -> RateLimitConfig:
        return RateLimitConfig(
            enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true",
            max_requests_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
            max_requests_per_hour=int(os.getenv("RATE_LIMIT_PER_HOUR", "1000")),
            max_tokens_per_day=int(os.getenv("RATE_LIMIT_TOKENS_PER_DAY", "100000"))
        )


config = AppConfig()