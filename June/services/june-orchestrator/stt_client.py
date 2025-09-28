# June/services/june-orchestrator/external_stt_client.py
import os
import asyncio
import httpx
import logging
from typing import Optional, Dict, Any, BinaryIO
from pathlib import Path
import tempfile
import base64

logger = logging.getLogger(__name__)

class ExternalSTTClient:
    """Client for communicating with external June STT service"""
    
    def __init__(self):
        self.stt_url = os.getenv("EXTERNAL_STT_URL", "https://your-stt-domain.com")
        self.timeout = httpx.Timeout(120.0, connect=10.0)  # Longer timeout for transcription
        self.service_client_id = os.getenv("KEYCLOAK_CLIENT_ID", "june-orchestrator")
        self.service_client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")
        self.keycloak_url = os.getenv("KEYCLOAK_URL", "https://idp.allsafe.world")
        self.keycloak_realm = os.getenv("KEYCLOAK_REALM", "allsafe")
        
        # Cache for service tokens
        self._service_token = None
        self._token_expires_at = 0
        
    async def _get_service_token(self) -> str:
        """Get service-to-service authentication token"""
        import time
        
        # Check if we have a valid cached token
        if self._service_token and time.time() < self._token_expires_at:
            return self._service_token
        
        token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"
        
        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.service_client_id,
                "client_secret": self.service_client_secret,
                "scope": "stt:transcribe stt:read"
            }
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                self._service_token = token_data["access_token"]
                
                # Cache token with 5 minute buffer
                expires_in = token_data.get("expires_in", 3600)
                self._token_expires_at = time.time() + expires_in - 300
                
                logger.debug("✅ Service token obtained for STT communication")
                return self._service_token
                
        except Exception as e:
            logger.error(f"❌ Failed to get service token: {e}")
            raise Exception(f"STT authentication failed: {e}")
    
    async def get_status(self) -> Dict[str, Any]:
        """Get external STT service status"""
        try:
            # Try without authentication first (health check)
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(f"{self.stt_url}/healthz")
                
                if response.status_code == 200:
                    # Get detailed status with authentication
                    try:
                        token = await self._get_service_token()
                        headers = {"Authorization": f"Bearer {token}"}
                        
                        status_response = await client.get(
                            f"{self.stt_url}/v1/status",
                            headers=headers
                        )
                        
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            return {
                                "available": True,
                                "status": "healthy",
                                "external_service": True,
                                "url": self.stt_url,
                                **status_data
                            }
                    except Exception as e:
                        logger.warning(f"Could not get detailed STT status: {e}")
                    
                    return {
                        "available": True,
                        "status": "healthy", 
                        "external_service": True,
                        "url": self.stt_url,
                        "note": "Basic health check only"
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
    
    async def transcribe_audio(
        self, 
        audio_data: bytes,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        task: str = "transcribe",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe audio using external STT service
        
        Args:
            audio_data: Audio file binary data
            filename: Original filename for content type detection
            language: Source language (optional, auto-detected if not provided)
            task: 'transcribe' or 'translate' (to English)
            user_id: User ID for tracking
        """
        try:
            # Get authentication token
            token = await self._get_service_token()
            
            # Prepare headers
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "june-orchestrator/3.1.0"
            }
            
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
                logger.info(f"🎤 Sending audio to external STT service: {self.stt_url}")
                
                response = await client.post(
                    f"{self.stt_url}/v1/transcribe",
                    files=files,
                    data=data,
                    headers=headers
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
                elif response.status_code == 401:
                    # Clear cached token and retry once
                    self._service_token = None
                    self._token_expires_at = 0
                    
                    logger.warning("Authentication failed, retrying with new token...")
                    token = await self._get_service_token()
                    headers["Authorization"] = f"Bearer {token}"
                    
                    retry_response = await client.post(
                        f"{self.stt_url}/v1/transcribe",
                        files=files,
                        data=data,
                        headers=headers
                    )
                    
                    if retry_response.status_code == 200:
                        result = retry_response.json()
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
                        error_msg = f"STT service authentication failed: {retry_response.status_code}"
                        logger.error(f"❌ {error_msg}")
                        return {"success": False, "error": error_msg}
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
    
    async def transcribe_audio_from_url(
        self,
        audio_url: str,
        language: Optional[str] = None,
        task: str = "transcribe",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Transcribe audio from URL"""
        try:
            # Download audio first
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.get(audio_url)
                response.raise_for_status()
                
                audio_data = response.content
                filename = audio_url.split("/")[-1] or "audio.wav"
                
                return await self.transcribe_audio(
                    audio_data=audio_data,
                    filename=filename,
                    language=language,
                    task=task,
                    user_id=user_id
                )
                
        except Exception as e:
            error_msg = f"Failed to download audio from URL: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
    
    async def transcribe_audio_from_base64(
        self,
        audio_b64: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        task: str = "transcribe",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Transcribe audio from base64 string"""
        try:
            audio_data = base64.b64decode(audio_b64)
            
            return await self.transcribe_audio(
                audio_data=audio_data,
                filename=filename,
                language=language,
                task=task,
                user_id=user_id
            )
            
        except Exception as e:
            error_msg = f"Failed to decode base64 audio: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}
    
    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
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

# Global external STT client instance
_external_stt_client: Optional[ExternalSTTClient] = None

def get_external_stt_client() -> ExternalSTTClient:
    """Get global external STT client instance"""
    global _external_stt_client
    if _external_stt_client is None:
        _external_stt_client = ExternalSTTClient()
    return _external_stt_client