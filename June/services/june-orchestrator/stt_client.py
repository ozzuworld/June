# June/services/june-orchestrator/stt_client.py
import os
import asyncio
import httpx
import logging
from typing import Optional, Dict, Any, BinaryIO
from pathlib import Path

logger = logging.getLogger(__name__)

class STTClient:
    """Client for communicating with June STT service"""
    
    def __init__(self):
        self.stt_url = os.getenv("STT_SERVICE_URL", "http://june-stt:8080")
        self.timeout = httpx.Timeout(60.0, connect=10.0)  # Longer timeout for transcription
        self.api_key = os.getenv("STT_API_KEY", "")
        
    async def get_status(self) -> Dict[str, Any]:
        """Get STT service status"""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.stt_url}/v1/status")
                
                if response.status_code == 200:
                    status_data = response.json()
                    return {
                        "available": True,
                        "status": status_data.get("status", "unknown"),
                        "features": status_data.get("features", {}),
                        "model": status_data.get("model", {}),
                        "url": self.stt_url
                    }
                else:
                    return {
                        "available": False, 
                        "error": f"Status check failed: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.warning(f"STT status check failed: {e}")
            return {"available": False, "error": str(e)}
    
    async def transcribe_audio(
        self, 
        audio_file: BinaryIO,
        filename: str,
        language: Optional[str] = None,
        task: str = "transcribe",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe audio file using STT service
        
        Args:
            audio_file: Audio file binary data
            filename: Original filename for content type detection
            language: Source language (optional, auto-detected if not provided)
            task: 'transcribe' or 'translate' (to English)
            user_id: User ID for tracking
        """
        try:
            # Prepare headers
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            # Prepare form data
            files = {
                "audio_file": (filename, audio_file, self._get_content_type(filename))
            }
            
            data = {
                "task": task,
                "notify_orchestrator": "true"
            }
            
            if language:
                data["language"] = language
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
                        "confidence": result.get("confidence")
                    }
                else:
                    error_msg = f"STT service returned {response.status_code}"
                    try:
                        error_detail = response.json().get("detail", "Unknown error")
                        error_msg = f"{error_msg}: {error_detail}"
                    except:
                        error_msg = f"{error_msg}: {response.text[:200]}"
                    
                    logger.error(f"❌ STT transcription failed: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
                    
        except Exception as e:
            logger.error(f"❌ STT transcription error: {e}")
            return {
                "success": False,
                "error": f"Transcription failed: {str(e)}"
            }
    
    async def get_transcript(self, transcript_id: str) -> Dict[str, Any]:
        """Get transcript by ID"""
        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(
                    f"{self.stt_url}/v1/transcripts/{transcript_id}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": f"Transcript not found: {response.status_code}"}
                    
        except Exception as e:
            logger.error(f"❌ Failed to get transcript {transcript_id}: {e}")
            return {"error": str(e)}
    
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

# Global STT client instance
_stt_client: Optional[STTClient] = None

def get_stt_client() -> STTClient:
    """Get global STT client instance"""
    global _stt_client
    if _stt_client is None:
        _stt_client = STTClient()
    return _stt_client