"""TTS orchestration service - Phase 2 extraction"""
import logging
from typing import Dict, Any, Optional, List
import httpx

from ...voice_registry import resolve_voice_reference, validate_voice_reference

logger = logging.getLogger(__name__)


class TTSOrchestrator:
    """Orchestrates TTS calls with voice cloning policies"""
    
    def __init__(self, tts_base_url: str, voice_profile_service):
        self.tts_base_url = tts_base_url.rstrip('/')
        self.voice_profile_service = voice_profile_service
    
    def _clamp(self, value: float, lo: float, hi: float) -> float:
        """Clamp value between bounds"""
        return max(lo, min(hi, value))
    
    async def trigger_streaming_tts(
        self, 
        room_name: str, 
        text: str, 
        language: str = "en",
        use_voice_cloning: bool = False, 
        user_id: Optional[str] = None,
        speaker: Optional[str] = None, 
        speaker_wav: Optional[str] = None,
        exaggeration: float = 0.6, 
        cfg_weight: float = 0.8
    ) -> Dict[str, Any]:
        """Trigger streaming TTS with voice cloning policy"""
        try:
            url = f"{self.tts_base_url}/stream-to-room"
            
            # Build payload - only include speaker_wav if voice cloning is requested
            payload = {
                "text": text,
                "language": language,
                "exaggeration": self._clamp(exaggeration, 0.0, 2.0),
                "cfg_weight": self._clamp(cfg_weight, 0.1, 1.0)
            }
            
            # Only add speaker_wav for voice cloning (mockingbird skill)
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
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=payload)
            
            if r.status_code == 200:
                res = r.json()
                logger.info(f"✅ Streaming TTS: first_audio={res.get('first_audio_ms', 0)}ms total={res.get('total_time_ms', 0)}ms")
                return {"success": True, **res}
            
            logger.error(f"❌ Streaming TTS failed: {r.status_code} {r.text}")
            return {"success": False, "error": f"TTS HTTP {r.status_code}"}
            
        except Exception as e:
            logger.error(f"❌ Streaming TTS error: {e}")
            return {"success": False, "error": str(e)}
    
    async def trigger_regular_tts(
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
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """Trigger regular TTS with voice cloning policy"""
        try:
            url = f"{self.tts_base_url}/publish-to-room"
            
            # Build payload - only include speaker_wav if voice cloning is requested
            payload = {
                "text": text,
                "language": language,
                "speed": speed,
                "exaggeration": self._clamp(exaggeration, 0.0, 2.0),
                "cfg_weight": self._clamp(cfg_weight, 0.1, 1.0),
                "streaming": False
            }
            
            # Only add speaker_wav for voice cloning (mockingbird skill)
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
                logger.info(f"✅ Regular TTS completed: {len(text)} chars")
                return {"success": True, **res}
            
            logger.error(f"❌ Regular TTS failed: {r.status_code} {r.text}")
            return {"success": False, "error": f"TTS HTTP {r.status_code}"}
            
        except Exception as e:
            logger.error(f"❌ Regular TTS error: {e}")
            return {"success": False, "error": str(e)}
    
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
        """Trigger TTS (streaming or regular) with voice cloning policy"""
        if streaming:
            return await self.trigger_streaming_tts(
                room_name, text, language, use_voice_cloning, user_id,
                speaker, speaker_wav, exaggeration, cfg_weight
            )
        else:
            return await self.trigger_regular_tts(
                room_name, text, language, use_voice_cloning, user_id,
                speaker, speaker_wav, exaggeration, cfg_weight, speed
            )