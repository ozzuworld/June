# Enhanced STT Service Integration for Context Awareness
# File: June/services/june-stt/context_aware_stt.py

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import json
import re

logger = logging.getLogger(__name__)

class ContextAwareSTTProcessor:
    """STT processor with conversation context awareness for accent correction"""
    
    def __init__(self, redis_client, orchestrator_client):
        self.redis = redis_client
        self.orchestrator = orchestrator_client
        self.active_contexts = {}  # session_id -> context
        
        # Technical vocabulary corrections specifically for Latin accent
        self.technical_corrections = {
            # Mathematics terms
            "square root": {
                "variations": ["square root", "скуэр рут", "raíz cuadrada", "skuer root", "square rut", "squere root"],
                "confidence_boost": 0.9
            },
            "algorithm": {
                "variations": ["algorithm", "алгоритм", "algoritmo", "algoridm", "algoritm", "algarithm"],
                "confidence_boost": 0.8
            },
            "function": {
                "variations": ["function", "функция", "función", "funccion", "funtions"],
                "confidence_boost": 0.8
            },
            "python": {
                "variations": ["python", "питон", "pitón", "piton", "pyton", "pythong"],
                "confidence_boost": 0.7
            },
            "kubernetes": {
                "variations": ["kubernetes", "кубернетес", "kubernete", "kubernet", "kubernets"],
                "confidence_boost": 0.9
            },
            # Common greetings that get misheard
            "hey june": {
                "variations": ["hey june", "Дмитрий", "hey dmitriy", "ay june", "ey june", "hey you"],
                "confidence_boost": 0.95
            },
            "hello june": {
                "variations": ["hello june", "hola como", "hola june", "alo june"],
                "confidence_boost": 0.9
            }
        }
        
        # Context hints for better transcription
        self.context_vocabulary = {
            "mathematics": ["number", "calculate", "equation", "math", "multiply", "divide", "add", "subtract"],
            "programming": ["code", "script", "variable", "class", "method", "import", "debug", "compile"],
            "devops": ["deploy", "container", "service", "pod", "cluster", "namespace", "helm", "yaml"]
        }
    
    async def process_audio_with_context(self, session_id: str, audio_data: bytes, 
                                       transcript: str) -> Dict:
        """Process audio with conversation context and accent correction"""
        try:
            # Step 1: Get conversation context from Redis
            context = await self.get_conversation_context(session_id)
            
            # Step 2: Apply context-aware corrections
            enhanced_transcript = await self.enhance_transcript_with_context(
                transcript, context
            )
            
            # Step 3: Apply technical vocabulary corrections
            corrected_transcript = self.apply_technical_corrections(
                enhanced_transcript, context
            )
            
            # Step 4: Store the enhanced transcript
            await self.store_enhanced_transcript(session_id, corrected_transcript, context, transcript)
            
            # Step 5: Send to orchestrator with context
            result = await self.send_to_orchestrator(session_id, corrected_transcript, context)
            
            # Log improvements if any corrections were made
            if corrected_transcript != transcript:
                logger.info(
                    f"STT Context Enhancement: '{transcript}' -> '{corrected_transcript}' "
                    f"(session: {session_id})"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Context-aware STT processing failed: {e}")
            # Fallback to basic processing
            return {
                "transcript": transcript, 
                "session_id": session_id,
                "enhanced": False,
                "error": str(e)
            }
    
    async def get_conversation_context(self, session_id: str) -> Dict:
        """Get recent conversation context for better transcription"""
        try:
            # Get recent conversation turns
            memory_key = f"conversation_memory:{session_id}"
            memory_data = await self.redis.get(memory_key)
            
            if not memory_data:
                return {
                    "topics": [], 
                    "recent_words": [], 
                    "context_hints": [],
                    "conversation_style": "neutral"
                }
            
            memory = json.loads(memory_data)
            recent_turns = memory.get("turns", [])[-5:]  # Last 5 turns
            
            # Extract context hints for better STT
            topics = memory.get("topics_discussed", [])
            recent_words = []
            context_hints = []
            
            for turn in recent_turns:
                content = turn.get("content", "")
                recent_words.extend(content.split()[-10:])  # Last 10 words per turn
                
                # Detect technical vocabulary usage
                content_lower = content.lower()
                for category, keywords in self.context_vocabulary.items():
                    if any(keyword in content_lower for keyword in keywords):
                        context_hints.append(category)
                
                # Detect if user asks about specific technical terms
                for term in self.technical_corrections.keys():
                    if term.lower() in content_lower:
                        context_hints.append(f"expects_{term.replace(' ', '_')}")
            
            return {
                "topics": topics,
                "recent_words": list(set(recent_words)),
                "context_hints": list(set(context_hints)),
                "last_interaction": memory.get("last_interaction"),
                "conversation_style": memory.get("conversation_style", "neutral")
            }
            
        except Exception as e:
            logger.warning(f"Failed to get conversation context: {e}")
            return {"topics": [], "recent_words": [], "context_hints": []}
    
    async def enhance_transcript_with_context(self, transcript: str, context: Dict) -> str:
        """Enhance transcript using conversation context"""
        try:
            enhanced = transcript
            context_hints = context.get("context_hints", [])
            recent_words = context.get("recent_words", [])
            
            # Context-based word substitutions
            if "mathematics" in context_hints:
                # Mathematical context - prioritize math terms
                math_substitutions = {
                    "скуэр рут": "square root",
                    "квадратный корень": "square root", 
                    "рут": "root",
                    "нумбер": "number",
                    "калкулейт": "calculate"
                }
                
                for foreign_term, english_term in math_substitutions.items():
                    if foreign_term.lower() in enhanced.lower():
                        pattern = re.compile(re.escape(foreign_term), re.IGNORECASE)
                        enhanced = pattern.sub(english_term, enhanced)
                        logger.info(f"Math context correction: {foreign_term} -> {english_term}")
            
            if "programming" in context_hints:
                # Programming context - prioritize code terms
                prog_substitutions = {
                    "функция": "function",
                    "класс": "class",
                    "метод": "method",
                    "переменная": "variable",
                    "скрипт": "script"
                }
                
                for foreign_term, english_term in prog_substitutions.items():
                    if foreign_term.lower() in enhanced.lower():
                        pattern = re.compile(re.escape(foreign_term), re.IGNORECASE)
                        enhanced = pattern.sub(english_term, enhanced)
                        logger.info(f"Programming context correction: {foreign_term} -> {english_term}")
            
            if "devops" in context_hints:
                # DevOps context - prioritize container/k8s terms
                devops_substitutions = {
                    "контейнер": "container",
                    "сервис": "service",
                    "под": "pod",
                    "кластер": "cluster",
                    "деплой": "deploy"
                }
                
                for foreign_term, english_term in devops_substitutions.items():
                    if foreign_term.lower() in enhanced.lower():
                        pattern = re.compile(re.escape(foreign_term), re.IGNORECASE)
                        enhanced = pattern.sub(english_term, enhanced)
                        logger.info(f"DevOps context correction: {foreign_term} -> {english_term}")
            
            # Topic continuity enhancement
            topics = context.get("topics", [])
            if topics and len(enhanced.split()) < 5:
                # Short response might be related to recent topic
                last_topic = topics[-1] if topics else None
                if last_topic and last_topic in ["mathematics", "programming", "devops"]:
                    # Add context hint for orchestrator
                    enhanced = f"{enhanced} [context: {last_topic}]"
                    logger.debug(f"Added topic context hint: {last_topic}")
            
            return enhanced
            
        except Exception as e:
            logger.error(f"Transcript enhancement failed: {e}")
            return transcript
    
    def apply_technical_corrections(self, transcript: str, context: Dict) -> str:
        """Apply technical vocabulary corrections based on context"""
        try:
            corrected = transcript
            corrections_applied = []
            
            for correct_term, term_data in self.technical_corrections.items():
                variations = term_data["variations"]
                
                # Check each variation
                for variation in variations[1:]:  # Skip first (correct) term
                    if variation.lower() in corrected.lower():
                        # Case-preserving replacement
                        pattern = re.compile(re.escape(variation), re.IGNORECASE)
                        
                        # Only replace if it makes sense in context
                        if self._should_apply_correction(correct_term, variation, context):
                            corrected = pattern.sub(correct_term, corrected)
                            corrections_applied.append(f"{variation} -> {correct_term}")
                            logger.info(f"Technical correction applied: {variation} -> {correct_term}")
            
            if corrections_applied:
                logger.info(f"Applied {len(corrections_applied)} technical corrections: {corrections_applied}")
            
            return corrected
            
        except Exception as e:
            logger.error(f"Technical corrections failed: {e}")
            return transcript
    
    def _should_apply_correction(self, correct_term: str, variation: str, context: Dict) -> bool:
        """Determine if a correction should be applied based on context"""
        try:
            # Always apply corrections for common misheard greetings
            if correct_term in ["hey june", "hello june"]:
                return True
            
            # Apply math corrections if in mathematical context
            if correct_term == "square root" and "mathematics" in context.get("context_hints", []):
                return True
            
            # Apply programming corrections if in programming context
            if correct_term in ["function", "python", "algorithm"] and "programming" in context.get("context_hints", []):
                return True
            
            # Apply DevOps corrections if in DevOps context
            if correct_term == "kubernetes" and "devops" in context.get("context_hints", []):
                return True
            
            # Default: apply if variation is clearly wrong (non-English)
            if any(char in variation for char in "абвгдежзийклмнопрстуфхцчшщъыьэюяáéíóúñü"):
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Correction decision failed: {e}")
            return True  # Default to applying correction
    
    async def store_enhanced_transcript(self, session_id: str, enhanced_transcript: str, 
                                      context: Dict, original_transcript: str):
        """Store enhanced transcript for future context and debugging"""
        try:
            transcript_data = {
                "session_id": session_id,
                "original_transcript": original_transcript,
                "enhanced_transcript": enhanced_transcript,
                "timestamp": datetime.utcnow().isoformat(),
                "context_used": context,
                "corrections_applied": enhanced_transcript != original_transcript,
                "enhancement_type": "context_aware_stt"
            }
            
            # Store in recent transcripts list for debugging
            key = f"enhanced_transcripts:{session_id}"
            await self.redis.lpush(key, json.dumps(transcript_data))
            await self.redis.ltrim(key, 0, 49)  # Keep last 50
            await self.redis.expire(key, 3600)  # 1 hour TTL
            
            # Update context vocabulary based on successful corrections
            if enhanced_transcript != original_transcript:
                await self._update_context_vocabulary(session_id, enhanced_transcript)
            
        except Exception as e:
            logger.warning(f"Failed to store enhanced transcript: {e}")
    
    async def _update_context_vocabulary(self, session_id: str, transcript: str):
        """Update context vocabulary based on successful transcriptions"""
        try:
            # Extract technical terms from successful transcription
            transcript_lower = transcript.lower()
            found_terms = []
            
            for term in self.technical_corrections.keys():
                if term.lower() in transcript_lower:
                    found_terms.append(term)
            
            if found_terms:
                # Store user's vocabulary preferences
                vocab_key = f"user_vocabulary:{session_id}"
                await self.redis.sadd(vocab_key, *found_terms)
                await self.redis.expire(vocab_key, 86400)  # 24 hour TTL
                
                logger.debug(f"Updated vocabulary context for {session_id}: {found_terms}")
            
        except Exception as e:
            logger.warning(f"Failed to update context vocabulary: {e}")
    
    async def send_to_orchestrator(self, session_id: str, transcript: str, context: Dict) -> Dict:
        """Send enhanced transcript to orchestrator with context"""
        try:
            payload = {
                "session_id": session_id,
                "transcript": transcript,
                "context": context,
                "enhanced": True,
                "timestamp": datetime.utcnow().isoformat(),
                "stt_processor": "context_aware"
            }
            
            # This would integrate with your existing STT->Orchestrator webhook
            # Replace with your actual orchestrator endpoint call
            response = await self.orchestrator.post("/api/webhooks/stt", json=payload)
            
            logger.info(f"Sent enhanced transcript to orchestrator: {session_id}")
            return response
            
        except Exception as e:
            logger.error(f"Failed to send to orchestrator: {e}")
            raise
    
    async def get_enhancement_stats(self, session_id: str) -> Dict:
        """Get statistics about transcript enhancements for this session"""
        try:
            key = f"enhanced_transcripts:{session_id}"
            transcript_data = await self.redis.lrange(key, 0, -1)
            
            if not transcript_data:
                return {"total_transcripts": 0, "corrections_applied": 0, "correction_rate": 0.0}
            
            total = len(transcript_data)
            corrections = 0
            
            for data_json in transcript_data:
                data = json.loads(data_json)
                if data.get("corrections_applied", False):
                    corrections += 1
            
            return {
                "total_transcripts": total,
                "corrections_applied": corrections,
                "correction_rate": corrections / total if total > 0 else 0.0,
                "session_id": session_id
            }
            
        except Exception as e:
            logger.error(f"Failed to get enhancement stats: {e}")
            return {"error": str(e)}

# Integration example for your existing STT service:
"""
# Add to your june-stt main processing:

from .context_aware_stt import ContextAwareSTTProcessor
import redis.asyncio as redis
import httpx

class STTService:
    def __init__(self):
        # ... existing init ...
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'redis'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            encoding='utf-8',
            decode_responses=True
        )
        
        self.orchestrator_client = httpx.AsyncClient(
            base_url=os.getenv('ORCHESTRATOR_URL', 'http://june-orchestrator:8000')
        )
        
        self.context_processor = ContextAwareSTTProcessor(
            redis_client=self.redis_client,
            orchestrator_client=self.orchestrator_client
        )
    
    async def process_audio(self, session_id: str, audio_data: bytes):
        # ... existing STT processing ...
        transcript = await self.transcribe(audio_data)
        
        # Enhanced processing with context
        result = await self.context_processor.process_audio_with_context(
            session_id, audio_data, transcript
        )
        
        return result
"""

# Usage in webhook endpoint:
"""
@app.post("/api/stt/webhook")
async def stt_webhook(session_id: str, audio_data: bytes):
    result = await stt_service.process_audio(session_id, audio_data)
    return result
"""