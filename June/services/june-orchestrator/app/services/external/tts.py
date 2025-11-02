"""TTS service client - Phase 1 refactor"""
import logging
from typing import Dict, Any, Optional, List
import httpx

logger = logging.getLogger(__name__)


class TTSClient:
    """Clean TTS service client"""
    
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        
        logger.info(f"✅ TTSClient initialized with URL: {base_url}")
    
    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        speaker_wav: Optional[List[str]] = None,
        speed: float = 1.0,
        exaggeration: float = 0.6,
        cfg_weight: float = 0.8,
        streaming: bool = False
    ) -> Dict[str, Any]:
        """Publish TTS audio to LiveKit room"""
        try:
            url = f"{self.base_url}/publish-to-room"
            
            payload = {
                "text": text,
                "language": language,
                "speed": speed,
                "exaggeration": max(0.0, min(2.0, exaggeration)),
                "cfg_weight": max(0.1, min(1.0, cfg_weight)),
                "streaming": streaming
            }
            
            # Only add speaker_wav if provided (for voice cloning)
            if speaker_wav:
                payload["speaker_wav"] = speaker_wav
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ TTS published to room {room_name}: {len(text)} chars")
                return {"success": True, **result}
            else:
                logger.error(f"❌ TTS failed: {response.status_code} {response.text}")
                return {"success": False, "error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")
            return {"success": False, "error": str(e)}
    
    async def stream_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        speaker_wav: Optional[List[str]] = None,
        exaggeration: float = 0.6,
        cfg_weight: float = 0.8
    ) -> Dict[str, Any]:
        """Stream TTS audio to LiveKit room"""
        try:
            url = f"{self.base_url}/stream-to-room"
            
            payload = {
                "text": text,
                "language": language,
                "exaggeration": max(0.0, min(2.0, exaggeration)),
                "cfg_weight": max(0.1, min(1.0, cfg_weight))
            }
            
            # Only add speaker_wav if provided (for voice cloning)
            if speaker_wav:
                payload["speaker_wav"] = speaker_wav
            
            async with httpx.AsyncClient(timeout=15.0) as client:  # Shorter timeout for streaming
                response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"✅ Streaming TTS: first_audio={result.get('first_audio_ms', 0)}ms "
                    f"total={result.get('total_time_ms', 0)}ms"
                )
                return {"success": True, **result}
            else:
                logger.error(f"❌ Streaming TTS failed: {response.status_code} {response.text}")
                return {"success": False, "error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ Streaming TTS error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_connection_info(self) -> Dict[str, str]:
        """Get TTS service connection information"""
        return {
            "tts_url": self.base_url,
            "timeout": str(self.timeout)
        }