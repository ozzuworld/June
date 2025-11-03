# Enhanced STT Service Integration for Context Awareness
# File: June/services/june-stt/context_aware_stt.py

import logging
from typing import Dict, Optional
from datetime import datetime
import json
import re

logger = logging.getLogger(__name__)

class ContextAwareSTTProcessor:
    def __init__(self, redis_client, orchestrator_client):
        self.redis = redis_client
        self.orchestrator = orchestrator_client
        self.technical_corrections = {
            "square root": {"variations": ["square root", "скуэр рут", "raíz cuadrada", "skuer root", "square rut"], "confidence_boost": 0.9},
            "algorithm": {"variations": ["algorithm", "алгоритм", "algoritmo", "algoridm", "algoritm"], "confidence_boost": 0.8},
            "function": {"variations": ["function", "функция", "función", "funccion"], "confidence_boost": 0.8},
            "python": {"variations": ["python", "питон", "pitón", "piton", "pyton"], "confidence_boost": 0.7},
            "kubernetes": {"variations": ["kubernetes", "кубернетес", "kubernete", "kubernets"], "confidence_boost": 0.9},
            "hey june": {"variations": ["hey june", "Дмитрий", "hey dmitriy", "ey june", "hey you"], "confidence_boost": 0.95}
        }
    
    async def process_audio_with_context(self, session_id: str, audio_data: bytes, transcript: str) -> Dict:
        context = await self.get_conversation_context(session_id)
        enhanced_transcript = await self.enhance_transcript_with_context(transcript, context)
        corrected_transcript = self.apply_technical_corrections(enhanced_transcript, context)
        await self.store_enhanced_transcript(session_id, corrected_transcript, context, transcript)
        result = await self.send_to_orchestrator(session_id, corrected_transcript, context)
        if corrected_transcript != transcript:
            logger.info(f"STT Context Enhancement: '{transcript}' -> '{corrected_transcript}' (session: {session_id})")
        return result

    async def get_conversation_context(self, session_id: str) -> Dict:
        memory_key = f"conversation_memory:{session_id}"
        memory_data = await self.redis.get(memory_key)
        if not memory_data:
            return {"topics": [], "recent_words": [], "context_hints": [], "conversation_style": "neutral"}
        memory = json.loads(memory_data)
        recent_turns = memory.get("turns", [])[-5:]
        topics = memory.get("topics_discussed", [])
        recent_words = []
        context_hints = []
        for turn in recent_turns:
            content = turn.get("content", "")
            recent_words.extend(content.split()[-10:])
            content_lower = content.lower()
            for keyword in ["number","calculate","equation","math","code","function","kubernetes","deploy"]:
                if keyword in content_lower:
                    context_hints.append(keyword)
            for term in self.technical_corrections.keys():
                if term.lower() in content_lower:
                    context_hints.append(f"expects_{term.replace(' ','_')}")
        return {"topics": topics, "recent_words": list(set(recent_words)), "context_hints": list(set(context_hints)), "last_interaction": memory.get("last_interaction"), "conversation_style": memory.get("conversation_style", "neutral")}

    async def enhance_transcript_with_context(self, transcript: str, context: Dict) -> str:
        enhanced = transcript
        if "math" in " ".join(context.get("context_hints", [])):
            subs = {"скуэр рут": "square root", "квадратный корень": "square root", "рут": "root"}
            for src, dst in subs.items():
                if src in enhanced.lower():
                    pattern = re.compile(re.escape(src), re.IGNORECASE)
                    enhanced = pattern.sub(dst, enhanced)
        topics = context.get("topics", [])
        if topics and len(enhanced.split()) < 5:
            last_topic = topics[-1]
            enhanced = f"{enhanced} [context: {last_topic}]"
        return enhanced

    def apply_technical_corrections(self, transcript: str, context: Dict) -> str:
        corrected = transcript
        for correct_term, term_data in self.technical_corrections.items():
            for variation in term_data["variations"][1:]:
                if variation.lower() in corrected.lower():
                    pattern = re.compile(re.escape(variation), re.IGNORECASE)
                    corrected = pattern.sub(correct_term, corrected)
        return corrected

    async def store_enhanced_transcript(self, session_id: str, enhanced_transcript: str, context: Dict, original_transcript: str):
        data = {"session_id": session_id, "original_transcript": original_transcript, "enhanced_transcript": enhanced_transcript, "timestamp": datetime.utcnow().isoformat(), "context_used": context, "corrections_applied": enhanced_transcript != original_transcript, "enhancement_type": "context_aware_stt"}
        key = f"enhanced_transcripts:{session_id}"
        await self.redis.lpush(key, json.dumps(data))
        await self.redis.ltrim(key, 0, 49)
        await self.redis.expire(key, 3600)

    async def send_to_orchestrator(self, session_id: str, transcript: str, context: Dict) -> Dict:
        payload = {"session_id": session_id, "transcript": transcript, "context": context, "enhanced": True, "timestamp": datetime.utcnow().isoformat(), "stt_processor": "context_aware"}
        response = await self.orchestrator.post("/api/webhooks/stt", json=payload)
        return response
