"""TTS orchestration service - cleaned to use publish-to-room only"""
import logging
from typing import Dict, Any, Optional
import httpx

from ...voice_registry import resolve_voice_reference, validate_voice_reference

logger = logging.getLogger(__name__)

class TTSOrchestrator:
    """Orchestrates TTS calls with voice cloning policies - publish-to-room only"""
    
    def __init__(self, tts_base_url: str, voice_profile_service):
        self.tts_base_url = tts_base_url.rstrip('/')
        self.voice_profile_service = voice_profile_service
    
    def _clamp(self, value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))
    
    async def trigger_tts(
        self, 
        room_name: str, 
        text: str, 
        language: str = "en",
        use_voice_cloning: bool = False, 
        user_id: Optional[str] = None,
        speaker: Optional[str] = None, 
        speaker_wav: Optional[str] = None,
        exaggeration: float = 0.6, 
        cfg_weight: float = 0.8,
        streaming: bool = False,
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """Publish TTS audio to a LiveKit room using publish-to-room endpoint"""
        try:
            url = f"{self.tts_base_url}/publish-to-room"
            payload = {
                "text": text,
                "language": language,
                "speed": speed,
                "exaggeration": self._clamp(exaggeration, 0.0, 2.0),
                "cfg_weight": self._clamp(cfg_weight, 0.1, 1.0),
                "streaming": bool(streaming)
            }
            
            if use_voice_cloning:
                if user_id:
                    refs = self.voice_profile_service.get_user_references(user_id)
                    if refs:
                        payload["speaker_wav"] = refs
                    else:
                        logger.warning(f"Voice cloning requested but no references found for user {user_id}")
                elif speaker_wav:
                    resolved = resolve_voice_reference(speaker, speaker_wav)
                    if resolved and validate_voice_reference(resolved):
                        payload["speaker_wav"] = [resolved]
                    else:
                        logger.warning(f"Voice cloning requested but invalid reference: {resolved}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json=payload)
            
            if r.status_code == 200:
                res = r.json()
                if streaming:
                    logger.info(f"✅ Streaming TTS published: first_audio={res.get('first_audio_ms', 0)}ms total={res.get('total_time_ms', 0)}ms")
                else:
                    logger.info(f"✅ Regular TTS published: {len(text)} chars")
                return {"success": True, **res}
            
            logger.error(f"❌ TTS publish failed: {r.status_code} {r.text}")
            return {"success": False, "error": f"TTS HTTP {r.status_code}"}
        
        except Exception as e:
            logger.error(f"❌ TTS publish error: {e}")
            return {"success": False, "error": str(e)}
