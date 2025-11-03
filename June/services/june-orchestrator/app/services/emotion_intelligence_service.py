# Week 3-4: Emotion Detection & Interruption Handling
# File: June/services/june-orchestrator/app/services/emotion_intelligence_service.py

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import base64

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

logger = logging.getLogger(__name__)

class EmotionIntelligenceService:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def analyze_voice_emotion(self, audio_data: Optional[bytes], session_id: str, transcript: Optional[str] = None) -> Dict[str, Any]:
        if not audio_data and transcript:
            return await self.analyze_text_emotion(transcript, session_id)
        if not audio_data:
            return {"emotion": "neutral", "confidence": 0.5}
        try:
            try:
                audio_bytes = base64.b64decode(audio_data)
            except Exception:
                audio_bytes = audio_data
            features = await self.extract_audio_features(audio_bytes)
            detected = self.classify_audio_emotion(features)
            await self.store_emotion_context(session_id, detected)
            return detected
        except Exception as e:
            logger.warning(f"Emotion analysis failed: {e}")
            return {"emotion": "neutral", "confidence": 0.5}

    async def analyze_text_emotion(self, transcript: str, session_id: str) -> Dict[str, Any]:
        t = transcript.lower()
        if any(w in t for w in ['confused','not working','error','wrong']):
            emotion, conf = 'frustrated', 0.8
        elif any(w in t for w in ['awesome','great','fantastic','wow','amazing','!']):
            emotion, conf = 'excited', 0.7
        elif any(w in t for w in ['maybe','not sure','i think','possibly','?']):
            emotion, conf = 'uncertain', 0.7
        elif any(w in t for w in ['how','what','why','explain','tell me']):
            emotion, conf = 'focused', 0.6
        else:
            emotion, conf = 'calm', 0.5
        detected = {"emotion": emotion, "confidence": conf, "method": "text"}
        await self.store_emotion_context(session_id, detected)
        return detected

    async def extract_audio_features(self, audio_bytes: bytes) -> Dict[str, float]:
        if NUMPY_AVAILABLE:
            arr = np.frombuffer(audio_bytes, dtype=np.float32)
            return {
                "energy": float(np.mean(np.abs(arr))) if arr.size else 0.01,
                "pitch_var": float(np.var(arr)) if arr.size else 20.0,
                "duration": len(audio_bytes) / 16000.0,
            }
        return {"energy": 0.01, "pitch_var": 20.0, "duration": 1.0}

    def classify_audio_emotion(self, f: Dict[str, float]) -> Dict[str, Any]:
        energy, var, dur = f.get('energy',0.01), f.get('pitch_var',20.0), f.get('duration',1.0)
        if energy > 0.02 and var > 50:
            emotion = 'frustrated' if dur > 3 else 'excited'; conf = 0.7
        elif energy < 0.01 and var < 25:
            emotion, conf = 'calm', 0.7
        elif var > 50 and energy < 0.02:
            emotion, conf = 'uncertain', 0.6
        else:
            emotion, conf = 'focused', 0.5
        return {"emotion": emotion, "confidence": conf, "method": "audio", "features_used": f}

    async def store_emotion_context(self, session_id: str, data: Dict):
        key = f"emotion_history:{session_id}"
        await self.redis.lpush(key, json.dumps({
            "emotion": data.get("emotion","neutral"),
            "confidence": data.get("confidence",0.5),
            "timestamp": datetime.utcnow().isoformat()
        }))
        await self.redis.ltrim(key, 0, 19)
        await self.redis.expire(key, 3600)

    def adapt_response_for_emotion(self, response: str, emotion: str, confidence: float) -> Dict[str, Any]:
        if confidence < 0.6:
            return {"adapted_response": response, "tone_adjustments": {"pace":"normal","tone":"neutral"}, "emotion_addressed": False}
        if emotion == 'frustrated' and not response.lower().startswith(("i understand","let me help")):
            response = f"I understand this might be frustrating. {response}"
        elif emotion == 'excited' and not any(w in response.lower() for w in ["great","awesome","exciting"]):
            response = f"I love your enthusiasm! {response}"
        elif emotion == 'uncertain' and not response.lower().startswith(("no worries","let me clarify")):
            response = f"No worries! {response}"
        elif emotion == 'focused' and not response.lower().startswith(("here's","let me explain")):
            response = f"Here's what you need to know: {response}"
        return {"adapted_response": response, "tone_adjustments": {"pace": "normal", "tone": emotion}, "emotion_addressed": True}

class InterruptionHandler:
    def __init__(self, redis_client, tts_service_client=None):
        self.redis = redis_client
        self.tts_service = tts_service_client
        self.active_responses = {}

    async def handle_interruption(self, session_id: str, room_name: str, user_input: Optional[str] = None) -> Dict[str, Any]:
        stop = await self.stop_current_response(session_id, room_name)
        await self.clear_response_queue(session_id)
        ack = await self.generate_ack(session_id, user_input)
        await self.store_interruption_event(session_id, user_input, ack)
        return {"interrupted": True, "acknowledgment": ack, "stopped_response": stop.get("stopped_response")}

    async def stop_current_response(self, session_id: str, room_name: str) -> Dict[str, Any]:
        active = self.active_responses.pop(session_id, None)
        tts_stopped = False
        if self.tts_service:
            try:
                res = await self.tts_service.stop_audio(room_name)
                tts_stopped = bool(res.get("success", False))
            except Exception:
                pass
        return {"stopped_response": (active or {}).get("content"), "tts_stopped": tts_stopped}

    async def clear_response_queue(self, session_id: str):
        await self.redis.delete(f"response_queue:{session_id}")
        await self.redis.delete(f"tts_queue:{session_id}")

    async def generate_ack(self, session_id: str, user_input: Optional[str] = None) -> str:
        if user_input:
            u = user_input.lower()
            if any(w in u for w in ['wait','stop','hold on']): return "Of course, I'll wait."
            if any(w in u for w in ['question','ask']): return "Yes, what's your question?"
            if any(w in u for w in ['different','actually','instead']): return "Sure, what would you like instead?"
        return "I'm listening."

    async def store_interruption_event(self, session_id: str, user_input: Optional[str], ack: str):
        key = f"interruptions:{session_id}"
        await self.redis.lpush(key, json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "user_input": user_input,
            "acknowledgment": ack
        }))
        await self.redis.ltrim(key, 0, 9)
        await self.redis.expire(key, 3600)

    def register_active_response(self, session_id: str, content: str, meta: Optional[Dict[str, Any]] = None):
        self.active_responses[session_id] = {"content": content, "meta": meta or {}, "start_time": datetime.utcnow()}

    def unregister_active_response(self, session_id: str):
        self.active_responses.pop(session_id, None)
