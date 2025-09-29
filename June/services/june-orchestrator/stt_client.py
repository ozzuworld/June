# June/services/june-orchestrator/stt_client.py
# STT Client with service-to-service authentication

import os
import asyncio
import httpx
import logging
from typing import Optional, Dict, Any
import base64

from service_auth import get_service_auth_headers

logger = logging.getLogger(__name__)


class ExternalSTTClient:
    """Client for communicating with external STT service"""
    
    def __init__(self):
        self.stt_url = os.getenv("EXTERNAL_STT_URL", "https://stt.allsafe.world")
        self.webhook_path = os.getenv("ORCHESTRATOR_WEBHOOK_PATH", "/v1/stt/webhook")
        self.timeout = httpx.Timeout(
            connect=5.0, 
            read=float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "120"))
        )
        self.enabled = os.getenv("ENABLE_ORCHESTRATOR_NOTIFICATIONS", "true").lower() == "true"
        self.max_retries = 3
        self.retry_delay = 1.0
    
    async def transcribe_audio(
        self, 
        audio_data: bytes,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        task: str = "transcribe"
    ) -> Dict[str, Any]:
        """
        Transcribe audio using external STT service with service authentication
        """
        try:
            # Get service authentication headers
            auth_headers = await get_service_auth_headers()
            
            # Prepare form data
            files = {
                "audio_file": (filename, audio_data, self._get_content_type(filename))
            }
            
            data = {
                "task": task,
                "notify_orchestrator": "true"
            }
            
            if language:
                data["language"] = language
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"🎤 Sending audio to STT service: {self.stt_url}")
                
                response = await client.post(
                    f"{self.stt_url}/v1/transcribe",
                    files=files,
                    data=data,
                    headers=auth_headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ Transcription completed: {result.get('transcript_id')}")
                    return {
                        "success": True,
                        "transcript_id": result.get("transcript_id"),
                        "text": result.get("text", ""),
                        "language": result.get("language"),
                        "processing_time_ms": result.get("processing_time_ms"),
                        "confidence": result.get("confidence"),
                        "external_service": True
                    }
                else:
                    error_msg = f"STT service returned {response.status_code}"
                    try:
                        error_detail = response.json().get("detail", "Unknown error")
                        error_msg = f"{error_msg}: {error_detail}"
                    except:
                        error_msg = f"{error_msg}: {response.text[:200]}"
                    
                    logger.error(f"❌ STT transcription failed: {error_msg}")
                    return {"success": False, "error": error_msg}
                    
        except httpx.TimeoutException:
            error_msg = "STT request timed out"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"STT transcription error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
    
    async def get_status(self) -> Dict[str, Any]:
        """Get external STT service status"""
        try:
            # Get service auth headers
            auth_headers = await get_service_auth_headers()
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(
                    f"{self.stt_url}/healthz",
                    headers=auth_headers
                )
                
                if response.status_code == 200:
                    return {
                        "available": True,
                        "status": "healthy",
                        "external_service": True,
                        "url": self.stt_url,
                        "authenticated": True
                    }
                else:
                    return {
                        "available": False,
                        "status": "unhealthy",
                        "external_service": True,
                        "url": self.stt_url,
                        "error": f"Health check failed: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.warning(f"STT status check failed: {e}")
            return {
                "available": False,
                "status": "unreachable",
                "external_service": True,
                "url": self.stt_url,
                "error": str(e)
            }
    
    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
        from pathlib import Path
        ext = Path(filename).suffix.lower()
        content_types = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg", 
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm"
        }
        return content_types.get(ext, "audio/wav")


# Global STT client instance
_stt_client: Optional[ExternalSTTClient] = None


def get_external_stt_client() -> ExternalSTTClient:
    """Get global external STT client instance"""
    global _stt_client
    if _stt_client is None:
        _stt_client = ExternalSTTClient()
    return _stt_client