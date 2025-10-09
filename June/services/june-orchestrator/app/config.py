"""
Configuration management for June Orchestrator
Handles WebRTC, services, and environment settings
"""
import os
import json
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
    ice_servers_json: Optional[str] = None


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
        
        # Log the actual WebRTC configuration for debugging
        logger.info(f"STUN servers configured: {len(self.webrtc.stun_servers)}")
        logger.info(f"TURN servers configured: {len(self.webrtc.turn_servers)}")
        if self.webrtc.stun_servers:
            logger.info(f"STUN servers: {', '.join(self.webrtc.stun_servers)}")
        if self.webrtc.turn_servers:
            logger.info(f"TURN servers: {', '.join(self.webrtc.turn_servers)}")
        if self.webrtc.turn_username:
            logger.info(f"TURN username: {self.webrtc.turn_username}")
    
    def _load_webrtc_config(self) -> WebRTCConfig:
        """Load WebRTC configuration from environment"""
        
        # ✅ FIX: Support both old and new environment variable formats
        # Check for K8s-style single server URLs first (current deployment)
        stun_server_url = os.getenv("STUN_SERVER_URL")  # K8s format: "stun:turn.ozzu.world:3478"
        turn_server_url = os.getenv("TURN_SERVER_URL")  # K8s format: "turn:turn.ozzu.world:3478"
        
        # Check for legacy comma-separated format
        stun_servers_str = os.getenv("STUN_SERVERS", "")
        turn_servers_str = os.getenv("TURN_SERVERS", "")
        
        # Build STUN servers list
        stun_servers = []
        if stun_server_url:
            stun_servers.append(stun_server_url)
            logger.info(f"Using K8s STUN server: {stun_server_url}")
        elif stun_servers_str:
            stun_servers = [s.strip() for s in stun_servers_str.split(",") if s.strip()]
            logger.info(f"Using legacy STUN servers: {stun_servers}")
        else:
            # Fallback to Google STUN
            stun_servers = ["stun:stun.l.google.com:19302"]
            logger.info("Using fallback Google STUN server")
        
        # Build TURN servers list
        turn_servers = []
        if turn_server_url:
            turn_servers.append(turn_server_url)
            logger.info(f"Using K8s TURN server: {turn_server_url}")
        elif turn_servers_str:
            turn_servers = [s.strip() for s in turn_servers_str.split(",") if s.strip()]
            logger.info(f"Using legacy TURN servers: {turn_servers}")
        
        # ✅ FIX: Support both TURN_CREDENTIAL (K8s) and TURN_PASSWORD (legacy)
        turn_username = os.getenv("TURN_USERNAME")
        turn_password = os.getenv("TURN_CREDENTIAL") or os.getenv("TURN_PASSWORD")  # K8s first, legacy fallback
        
        # Get ICE servers JSON if available (for direct client use)
        ice_servers_json = os.getenv("ICE_SERVERS")
        
        return WebRTCConfig(
            enabled=os.getenv("WEBRTC_ENABLED", "true").lower() == "true",
            audio_codec=os.getenv("WEBRTC_AUDIO_CODEC", "opus"),
            sample_rate=int(os.getenv("WEBRTC_SAMPLE_RATE", "48000")),
            channels=int(os.getenv("WEBRTC_CHANNELS", "1")),
            stun_servers=stun_servers,
            turn_servers=turn_servers,
            turn_username=turn_username,
            turn_password=turn_password,
            ice_servers_json=ice_servers_json
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
            tts_base_url=os.getenv("TTS_SERVICE_URL", "http://june-tts.june-services.svc.cluster.local:8000"),
            stt_base_url=os.getenv("STT_SERVICE_URL", "http://june-stt.june-services.svc.cluster.local:8080"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            stt_service_token=os.getenv("VALID_SERVICE_TOKENS")
        )
    
    def get_ice_servers(self) -> List[dict]:
        """Get ICE servers configuration for WebRTC"""
        # ✅ NEW: Try to use the pre-configured ICE_SERVERS JSON first
        if self.webrtc.ice_servers_json:
            try:
                ice_servers_from_json = json.loads(self.webrtc.ice_servers_json)
                logger.info(f"Using ICE servers from JSON config: {len(ice_servers_from_json)} servers")
                return ice_servers_from_json
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse ICE_SERVERS JSON: {e}")
        
        # Fallback: Build ICE servers from individual config
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
        
        logger.info(f"Built ICE servers from config: {len(ice_servers)} servers")
        return ice_servers
    
    def get_ice_servers_json(self) -> str:
        """Get ICE servers as JSON string for client-side use"""
        return json.dumps(self.get_ice_servers(), indent=2)


# Global config instance
config = AppConfig()