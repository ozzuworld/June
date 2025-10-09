"""
Configuration management for June Orchestrator
Handles WebRTC, services, and environment settings
"""
import os
from typing import List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class WebRTCConfig(BaseModel):
    """WebRTC configuration"""
    enabled: bool = True
    audio_codec: str = "opus"
    sample_rate: int = 48000
    channels: int = 1
    stun_servers: List[str] = []
    turn_servers: List[str] = []
    turn_username: Optional[str] = None
    turn_password: Optional[str] = None


class VADConfig(BaseModel):
    """Voice Activity Detection configuration"""
    enabled: bool = True
    aggressiveness: int = 3  # 0-3, higher = more aggressive
    frame_duration_ms: int = 30  # 10, 20, or 30ms


class ServiceConfig(BaseModel):
    """Service URLs and tokens"""
    tts_base_url: str
    stt_base_url: str
    gemini_api_key: Optional[str] = None
    stt_service_token: Optional[str] = None


class AppConfig:
    """Main application configuration"""
    
    def __init__(self):
        # Basic service config
        self.service_name = os.getenv("SERVICE_NAME", "june-orchestrator")
        self.port = int(os.getenv("PORT", "8080"))
        self.host = os.getenv("HOST", "0.0.0.0")
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # CORS
        cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
        self.cors_origins = [o.strip() for o in cors_origins.split(",")]
        
        # WebRTC configuration
        self.webrtc = self._load_webrtc_config()
        
        # VAD configuration
        self.vad = self._load_vad_config()
        
        # Service configuration
        self.services = self._load_service_config()
        
        logger.info(f"Configuration loaded for {self.environment} environment")
        logger.info(f"WebRTC enabled: {self.webrtc.enabled}")
        logger.info(f"VAD enabled: {self.vad.enabled}")
    
    def _load_webrtc_config(self) -> WebRTCConfig:
        """Load WebRTC configuration from environment"""
        stun_servers_str = os.getenv("STUN_SERVERS", "stun:stun.l.google.com:19302")
        stun_servers = [s.strip() for s in stun_servers_str.split(",") if s.strip()]
        
        turn_servers_str = os.getenv("TURN_SERVERS", "")
        turn_servers = [s.strip() for s in turn_servers_str.split(",") if s.strip()]
        
        return WebRTCConfig(
            enabled=os.getenv("WEBRTC_ENABLED", "true").lower() == "true",
            audio_codec=os.getenv("WEBRTC_AUDIO_CODEC", "opus"),
            sample_rate=int(os.getenv("WEBRTC_SAMPLE_RATE", "48000")),
            channels=int(os.getenv("WEBRTC_CHANNELS", "1")),
            stun_servers=stun_servers,
            turn_servers=turn_servers,
            turn_username=os.getenv("TURN_USERNAME"),
            turn_password=os.getenv("TURN_PASSWORD")
        )
    
    def _load_vad_config(self) -> VADConfig:
        """Load VAD configuration from environment"""
        return VADConfig(
            enabled=os.getenv("VAD_ENABLED", "true").lower() == "true",
            aggressiveness=int(os.getenv("VAD_AGGRESSIVENESS", "3")),
            frame_duration_ms=int(os.getenv("VAD_FRAME_DURATION", "30"))
        )
    
    def _load_service_config(self) -> ServiceConfig:
        """Load service URLs and credentials"""
        return ServiceConfig(
            tts_base_url=os.getenv("TTS_BASE_URL", "http://june-tts.june-services.svc.cluster.local:8000"),
            stt_base_url=os.getenv("STT_BASE_URL", "http://june-stt.june-services.svc.cluster.local:8080"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            stt_service_token=os.getenv("STT_SERVICE_TOKEN")
        )
    
    def get_ice_servers(self) -> List[dict]:
        """Get ICE servers configuration for WebRTC"""
        ice_servers = []
        
        # Add STUN servers
        for stun in self.webrtc.stun_servers:
            ice_servers.append({"urls": stun})
        
        # Add TURN servers
        if self.webrtc.turn_servers:
            for turn in self.webrtc.turn_servers:
                turn_config = {"urls": turn}
                if self.webrtc.turn_username and self.webrtc.turn_password:
                    turn_config["username"] = self.webrtc.turn_username
                    turn_config["credential"] = self.webrtc.turn_password
                ice_servers.append(turn_config)
        
        return ice_servers


# Global config instance
config = AppConfig()