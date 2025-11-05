"""STT service client - Phase 1 refactor"""
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class STTClient:
    """Clean STT service client"""
    
    def __init__(self, base_url: str, service_token: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.service_token = service_token
        self.timeout = timeout
        
        logger.info(f"✅ STTClient initialized with URL: {base_url}")
    
    async def transcribe_audio(
        self,
        audio_data: bytes,
        language: str = "en",
        model: str = "whisper"
    ) -> Dict[str, Any]:
        """Transcribe audio data"""
        try:
            url = f"{self.base_url}/transcribe"
            
            headers = {}
            if self.service_token:
                headers["Authorization"] = f"Bearer {self.service_token}"
            
            files = {"audio": audio_data}
            params = {
                "language": language,
                "model": model
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, files=files, params=params, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ STT transcribed: {len(result.get('text', ''))} chars")
                return {"success": True, **result}
            else:
                logger.error(f"❌ STT failed: {response.status_code} {response.text}")
                return {"success": False, "error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            logger.error(f"❌ STT error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_connection_info(self) -> Dict[str, str]:
        """Get STT service connection information"""
        return {
            "stt_url": self.base_url,
            "timeout": str(self.timeout),
            "authenticated": bool(self.service_token)
        }