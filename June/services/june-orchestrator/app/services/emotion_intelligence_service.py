# Week 3-4: Emotion Detection & Interruption Handling
# File: June/services/june-orchestrator/app/services/emotion_intelligence_service.py

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import json
import base64

# Optional audio processing - graceful fallback if not available
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    librosa = None

logger = logging.getLogger(__name__)

class EmotionIntelligenceService:
    """Detects emotion from voice and adapts responses accordingly"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Check audio processing capabilities
        if NUMPY_AVAILABLE and LIBROSA_AVAILABLE:
            self.audio_processing_enabled = True
            logger.info("✅ Audio emotion processing enabled with librosa")
        else:
            self.audio_processing_enabled = False
            logger.warning("⚠️ Audio emotion processing disabled - install librosa and numpy for enhanced features")
        
        # Simple emotion detection thresholds (enhance with actual ML model)
        self.emotion_features = {
            "energy_threshold": 0.02,  # For detecting excitement/anger
            "pitch_variance_threshold": 50,  # For detecting stress/uncertainty
            "speech_rate_threshold": 150,  # Words per minute
        }
        
        # Emotion-based response modifiers
        self.emotion_responses = {
            "excited": {
                "tone": "enthusiastic",
                "pace": "energetic", 
                "language_prefix": "Great! That's awesome! I love your enthusiasm about",
                "response_style": "match_energy"
            },
            "calm": {
                "tone": "gentle",
                "pace": "relaxed",
                "language_prefix": "That's a thoughtful question. Let me explain",
                "response_style": "measured"
            },
            "frustrated": {
                "tone": "understanding",
                "pace": "patient",
                "language_prefix": "I understand this can be confusing. Let me help break it down",
                "response_style": "reassuring"
            },
            "uncertain": {
                "tone": "reassuring",
                "pace": "clear",
                "language_prefix": "No worries! Let me explain this step by step",
                "response_style": "supportive"
            },
            "focused": {
                "tone": "professional",
                "pace": "precise",
                "language_prefix": "Here's the technical explanation you're looking for",
                "response_style": "detailed"
            },
            "neutral": {
                "tone": "friendly",
                "pace": "normal",
                "language_prefix": "",
                "response_style": "conversational"
            }
        }
    
    async def analyze_voice_emotion(self, audio_data: Optional[bytes], session_id: str, 
                                  transcript: Optional[str] = None) -> Dict[str, Any]:
        """Analyze emotion from voice audio and/or transcript"""
        try:
            # If no audio data, analyze from transcript
            if not audio_data and transcript:
                return await self.analyze_text_emotion(transcript, session_id)
            
            if not audio_data:
                return {"emotion": "neutral", "confidence": 0.5, "method": "default"}
            
            # Try audio analysis if available
            if self.audio_processing_enabled:
                try:
                    audio_emotion = await self.analyze_audio_emotion(audio_data, session_id)
                    if audio_emotion["confidence"] > 0.6:
                        return audio_emotion
                except Exception as e:
                    logger.warning(f"Audio emotion analysis failed, falling back to text: {e}")
            
            # Fallback to text analysis
            if transcript:
                return await self.analyze_text_emotion(transcript, session_id)
            
            # Final fallback
            return {"emotion": "neutral", "confidence": 0.5, "method": "fallback"}
            
        except Exception as e:
            logger.warning(f"Emotion analysis failed: {e}")
            return {"emotion": "neutral", "confidence": 0.5, "error": str(e)}
    
    async def analyze_audio_emotion(self, audio_data: bytes, session_id: str) -> Dict[str, Any]:
        """Analyze emotion from audio data (requires librosa)"""
        try:
            if not self.audio_processing_enabled:
                raise ValueError("Audio processing not available")
            
            # Decode audio data (assuming it's base64 encoded)
            try:
                audio_bytes = base64.b64decode(audio_data)
            except:
                # If not base64, assume raw bytes
                audio_bytes = audio_data
            
            # Basic audio feature extraction
            emotion_features = await self.extract_audio_emotion_features(audio_bytes)
            
            # Simple rule-based emotion detection (replace with ML model)
            detected_emotion = self.classify_audio_emotion(emotion_features)
            
            # Store emotion history
            await self.store_emotion_context(session_id, detected_emotion)
            
            logger.info(f"Detected audio emotion: {detected_emotion['emotion']} (confidence: {detected_emotion['confidence']:.2f})")
            
            return detected_emotion
            
        except Exception as e:
            logger.warning(f"Audio emotion analysis failed: {e}")
            raise
    
    async def analyze_text_emotion(self, transcript: str, session_id: str) -> Dict[str, Any]:
        """Analyze emotion from transcript text (fallback method)"""
        try:
            transcript_lower = transcript.lower()
            
            # Simple text-based emotion detection
            emotion = "neutral"
            confidence = 0.6
            indicators = []
            
            # Excitement indicators
            if any(word in transcript_lower for word in ['awesome', 'great', 'fantastic', '!', 'wow', 'amazing']):
                emotion = "excited"
                confidence = 0.7
                indicators.append("positive_language")
            
            # Frustration indicators
            elif any(word in transcript_lower for word in ['confused', 'don\'t understand', 'not working', 'wrong', 'error']):
                emotion = "frustrated"
                confidence = 0.8
                indicators.append("negative_language")
            
            # Uncertainty indicators
            elif any(word in transcript_lower for word in ['maybe', 'not sure', 'i think', 'possibly', '?']):
                emotion = "uncertain"
                confidence = 0.7
                indicators.append("uncertainty_markers")
            
            # Question/focused indicators
            elif any(word in transcript_lower for word in ['how', 'what', 'why', 'explain', 'tell me']):
                emotion = "focused"
                confidence = 0.6
                indicators.append("information_seeking")
            
            # Calm/thoughtful indicators
            elif len(transcript.split()) > 10 and not any(char in transcript for char in '!?'):
                emotion = "calm"
                confidence = 0.5
                indicators.append("measured_speech")
            
            detected_emotion = {
                "emotion": emotion,
                "confidence": confidence,
                "method": "text_analysis",
                "indicators": indicators,
                "transcript_analyzed": transcript[:100] + "..." if len(transcript) > 100 else transcript
            }
            
            # Store emotion history
            await self.store_emotion_context(session_id, detected_emotion)
            
            logger.info(f"Detected text emotion: {emotion} (confidence: {confidence:.2f}, indicators: {indicators})")
            
            return detected_emotion
            
        except Exception as e:
            logger.error(f"Text emotion analysis failed: {e}")
            return {"emotion": "neutral", "confidence": 0.5, "method": "error"}
    
    async def extract_audio_emotion_features(self, audio_bytes: bytes) -> Dict[str, float]:
        """Extract basic audio features for emotion detection"""
        try:
            # This is a simplified implementation
            # In production, use librosa for proper audio processing
            
            # Convert bytes to numpy array (simplified - needs proper audio parsing)
            if NUMPY_AVAILABLE:
                # Simplified feature extraction
                audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
                
                features = {
                    "energy": float(np.mean(np.abs(audio_array))) if len(audio_array) > 0 else 0.01,
                    "pitch_variance": float(np.var(audio_array)) if len(audio_array) > 0 else 20.0,
                    "duration": len(audio_bytes) / 16000.0,  # Assume 16kHz sample rate
                    "zero_crossing_rate": 0.1,  # Placeholder
                    "spectral_centroid": 1000.0,  # Placeholder
                }
            else:
                # Fallback features
                features = {
                    "energy": 0.01,
                    "pitch_variance": 20.0,
                    "duration": 1.0,
                    "zero_crossing_rate": 0.1,
                    "spectral_centroid": 1000.0
                }
            
            return features
            
        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}")
            return {
                "energy": 0.01,
                "pitch_variance": 20.0,
                "duration": 1.0,
                "zero_crossing_rate": 0.1,
                "spectral_centroid": 1000.0
            }
    
    def classify_audio_emotion(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Simple rule-based emotion classification from audio features"""
        try:
            energy = features.get("energy", 0.01)
            pitch_variance = features.get("pitch_variance", 20.0)
            duration = features.get("duration", 1.0)
            
            confidence = 0.6  # Base confidence
            
            # High energy + high pitch variance = excited/frustrated
            if energy > self.emotion_features["energy_threshold"] and pitch_variance > self.emotion_features["pitch_variance_threshold"]:
                if duration > 3.0:  # Longer speech = more likely frustrated
                    emotion = "frustrated"
                    confidence = 0.7
                else:
                    emotion = "excited"
                    confidence = 0.8
            
            # Low energy + low variance = calm
            elif energy < self.emotion_features["energy_threshold"] / 2 and pitch_variance < self.emotion_features["pitch_variance_threshold"] / 2:
                emotion = "calm"
                confidence = 0.7
            
            # High variance but low energy = uncertain
            elif pitch_variance > self.emotion_features["pitch_variance_threshold"] and energy < self.emotion_features["energy_threshold"]:
                emotion = "uncertain"
                confidence = 0.6
            
            # Moderate levels = focused
            else:
                emotion = "focused"
                confidence = 0.5
            
            return {
                "emotion": emotion,
                "confidence": confidence,
                "method": "audio_analysis",
                "features_used": features
            }
            
        except Exception as e:
            logger.error(f"Audio emotion classification failed: {e}")
            return {"emotion": "neutral", "confidence": 0.5, "method": "error"}
    
    async def store_emotion_context(self, session_id: str, emotion_data: Dict):
        """Store emotion context for conversation history"""
        try:
            emotion_history_key = f"emotion_history:{session_id}"
            
            emotion_entry = {
                "emotion": emotion_data["emotion"],
                "confidence": emotion_data["confidence"],
                "method": emotion_data.get("method", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "features": emotion_data.get("features_used", {})
            }
            
            # Store in Redis list
            await self.redis.lpush(emotion_history_key, json.dumps(emotion_entry))
            await self.redis.ltrim(emotion_history_key, 0, 19)  # Keep last 20 emotions
            await self.redis.expire(emotion_history_key, 3600)  # 1 hour TTL
            
        except Exception as e:
            logger.warning(f"Failed to store emotion context: {e}")
    
    async def get_emotion_context(self, session_id: str) -> List[Dict]:
        """Get recent emotion context for session"""
        try:
            emotion_history_key = f"emotion_history:{session_id}"
            history_data = await self.redis.lrange(emotion_history_key, 0, 4)  # Last 5 emotions
            
            emotions = []
            for entry in history_data:
                emotions.append(json.loads(entry))
            
            return emotions
            
        except Exception as e:
            logger.warning(f"Failed to get emotion context: {e}")
            return []
    
    def adapt_response_for_emotion(self, response: str, detected_emotion: str, 
                                 confidence: float) -> Dict[str, Any]:
        """Adapt response tone and content based on detected emotion"""
        try:
            if confidence < 0.6:
                # Low confidence, use neutral approach
                return {
                    "adapted_response": response,
                    "tone_adjustments": {"pace": "normal", "tone": "neutral"},
                    "emotion_addressed": False
                }
            
            emotion_config = self.emotion_responses.get(detected_emotion, self.emotion_responses["neutral"])
            adapted_response = response
            
            # Adapt response language based on emotion
            if detected_emotion == "frustrated":
                # Add empathy and reassurance
                if not response.lower().startswith(("i understand", "i see", "let me help")):
                    adapted_response = f"I understand this might be frustrating. {response}"
            
            elif detected_emotion == "excited":
                # Match enthusiasm
                if not any(word in response.lower() for word in ["great", "awesome", "exciting", "fantastic"]):
                    adapted_response = f"I love your enthusiasm! {response}"
            
            elif detected_emotion == "uncertain":
                # Add reassurance and clarity
                if not response.lower().startswith(("no worries", "don't worry", "let me clarify")):
                    adapted_response = f"No worries at all! {response}"
            
            elif detected_emotion == "calm":
                # Keep measured tone
                adapted_response = response  # Keep as is
            
            elif detected_emotion == "focused":
                # Provide clear, detailed response
                if not response.lower().startswith(("here's", "let me explain")):
                    adapted_response = f"Here's what you need to know: {response}"
            
            # TTS tone adjustments
            tone_adjustments = {
                "pace": emotion_config["pace"],
                "tone": emotion_config["tone"],
                "emotion": detected_emotion,
                "confidence": confidence,
                "response_style": emotion_config["response_style"]
            }
            
            return {
                "adapted_response": adapted_response,
                "tone_adjustments": tone_adjustments,
                "emotion_addressed": True,
                "original_emotion": detected_emotion,
                "adaptation_applied": adapted_response != response
            }
            
        except Exception as e:
            logger.error(f"Response adaptation failed: {e}")
            return {
                "adapted_response": response,
                "tone_adjustments": {"pace": "normal", "tone": "neutral"},
                "emotion_addressed": False
            }


class InterruptionHandler:
    """Handles conversation interruptions gracefully"""
    
    def __init__(self, redis_client, tts_service_client=None):
        self.redis = redis_client
        self.tts_service = tts_service_client
        self.active_responses = {}  # session_id -> response_info
        
        # Interruption acknowledgments
        self.acknowledgments = [
            "Yes?",
            "I'm listening.",
            "Go ahead.",
            "What's up?",
            "Yes, tell me.",
            "I'm here.",
            "Continue.",
            "What can I help with?"
        ]
        
    async def handle_interruption(self, session_id: str, room_name: str, 
                                user_input: Optional[str] = None) -> Dict[str, Any]:
        """Handle user interruption during AI response"""
        try:
            logger.info(f"Handling interruption for session {session_id}")
            
            # Stop current TTS if playing
            interruption_result = await self.stop_current_response(session_id, room_name)
            
            # Clear any queued responses
            await self.clear_response_queue(session_id)
            
            # Generate contextual acknowledgment
            acknowledgment = await self.generate_interruption_acknowledgment(
                session_id, user_input
            )
            
            # Store interruption event
            await self.store_interruption_event(session_id, user_input, acknowledgment)
            
            return {
                "interrupted": True,
                "session_id": session_id,
                "acknowledgment": acknowledgment,
                "stopped_response": interruption_result.get("stopped_response"),
                "timestamp": datetime.utcnow().isoformat(),
                "user_input": user_input
            }
            
        except Exception as e:
            logger.error(f"Interruption handling failed: {e}")
            return {"interrupted": False, "error": str(e)}
    
    async def stop_current_response(self, session_id: str, room_name: str) -> Dict[str, Any]:
        """Stop currently playing TTS response"""
        try:
            # Check if there's an active response
            active_response = self.active_responses.get(session_id)
            if not active_response:
                return {"stopped_response": None, "was_active": False}
            
            # Stop TTS service if available
            tts_result = {"success": False}
            if self.tts_service:
                try:
                    tts_result = await self.tts_service.stop_audio(room_name)
                except Exception as e:
                    logger.warning(f"TTS stop failed: {e}")
            
            # Remove from active responses
            stopped_response = self.active_responses.pop(session_id, None)
            
            logger.info(f"Stopped active response for session {session_id}")
            
            return {
                "stopped_response": stopped_response.get("content", "")[:100] + "..." if stopped_response else None,
                "was_active": True,
                "tts_stopped": tts_result.get("success", False),
                "interruption_time": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to stop current response: {e}")
            return {"stopped_response": None, "was_active": False, "error": str(e)}
    
    async def clear_response_queue(self, session_id: str):
        """Clear any queued responses for session"""
        try:
            # Clear from response queue
            queue_key = f"response_queue:{session_id}"
            await self.redis.delete(queue_key)
            
            # Clear any pending TTS tasks
            tts_queue_key = f"tts_queue:{session_id}"
            await self.redis.delete(tts_queue_key)
            
            logger.info(f"Cleared response queues for session {session_id}")
            
        except Exception as e:
            logger.warning(f"Failed to clear response queue: {e}")
    
    async def generate_interruption_acknowledgment(self, session_id: str, 
                                                 user_input: Optional[str] = None) -> str:
        """Generate natural acknowledgment of interruption"""
        try:
            # Get recent emotion context to tailor acknowledgment
            emotion_history_key = f"emotion_history:{session_id}"
            try:
                recent_emotions = await self.redis.lrange(emotion_history_key, 0, 0)
                if recent_emotions:
                    emotion_data = json.loads(recent_emotions[0])
                    last_emotion = emotion_data.get("emotion", "neutral")
                else:
                    last_emotion = "neutral"
            except:
                last_emotion = "neutral"
            
            # Choose acknowledgment based on emotion and input
            if user_input:
                user_lower = user_input.lower()
                if any(word in user_lower for word in ['wait', 'stop', 'hold on']):
                    return "Of course, I'll wait."
                elif any(word in user_lower for word in ['question', 'ask']):
                    return "Yes, what's your question?"
                elif any(word in user_lower for word in ['different', 'actually', 'instead']):
                    return "Sure, what would you like to know instead?"
            
            # Emotion-based acknowledgments
            if last_emotion == "frustrated":
                return "I'm here to help, what do you need?"
            elif last_emotion == "excited":
                return "Yes, I'm listening!"
            elif last_emotion == "uncertain":
                return "No problem, what can I clarify?"
            else:
                # Random natural acknowledgment
                import random
                return random.choice(self.acknowledgments)
                
        except Exception as e:
            logger.error(f"Failed to generate acknowledgment: {e}")
            return "Yes?"
    
    async def store_interruption_event(self, session_id: str, user_input: Optional[str], 
                                     acknowledgment: str):
        """Store interruption event for analytics"""
        try:
            interruption_data = {
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "user_input": user_input,
                "acknowledgment": acknowledgment,
                "event_type": "interruption"
            }
            
            # Store in interruption history
            key = f"interruptions:{session_id}"
            await self.redis.lpush(key, json.dumps(interruption_data))
            await self.redis.ltrim(key, 0, 9)  # Keep last 10
            await self.redis.expire(key, 3600)  # 1 hour TTL
            
        except Exception as e:
            logger.warning(f"Failed to store interruption event: {e}")
    
    def register_active_response(self, session_id: str, response_content: str, 
                               response_metadata: Optional[Dict] = None):
        """Register an active response that can be interrupted"""
        self.active_responses[session_id] = {
            "content": response_content,
            "start_time": datetime.utcnow(),
            "can_interrupt": True,
            "metadata": response_metadata or {}
        }
        
        logger.debug(f"Registered active response for {session_id}")
    
    def unregister_active_response(self, session_id: str):
        """Unregister active response when complete"""
        removed = self.active_responses.pop(session_id, None)
        if removed:
            logger.debug(f"Unregistered active response for {session_id}")
    
    async def get_interruption_stats(self, session_id: str) -> Dict[str, Any]:
        """Get interruption statistics for session"""
        try:
            key = f"interruptions:{session_id}"
            interruption_data = await self.redis.lrange(key, 0, -1)
            
            stats = {
                "total_interruptions": len(interruption_data),
                "session_id": session_id,
                "recent_interruptions": []
            }
            
            for data_json in interruption_data[:3]:  # Last 3
                data = json.loads(data_json)
                stats["recent_interruptions"].append({
                    "timestamp": data["timestamp"],
                    "acknowledgment": data["acknowledgment"]
                })
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get interruption stats: {e}")
            return {"error": str(e)}


# Integration example for your orchestrator:
"""
# In your orchestrator webhook handler:

emotion_service = EmotionIntelligenceService(redis_client)
interruption_handler = InterruptionHandler(redis_client, tts_client)

async def process_stt_webhook(session_id: str, transcript: str, audio_data: Optional[bytes] = None):
    # Detect emotion from audio/transcript
    emotion_result = await emotion_service.analyze_voice_emotion(
        audio_data, session_id, transcript
    )
    
    # Check for interruption
    if interruption_handler.active_responses.get(session_id):
        interruption_result = await interruption_handler.handle_interruption(
            session_id, room_name, transcript
        )
        if interruption_result["interrupted"]:
            # Send quick acknowledgment
            await tts_service.speak_immediately(
                interruption_result["acknowledgment"], 
                session_id
            )
            return interruption_result
    
    # Process conversation with emotion context
    response = await natural_conversation_processor.process_natural_conversation(
        session_id=session_id,
        user_message=transcript,
        audio_context=emotion_result
    )
    
    # Adapt response for detected emotion
    adapted = emotion_service.adapt_response_for_emotion(
        response["response"], 
        emotion_result["emotion"],
        emotion_result["confidence"]
    )
    
    # Register response for potential interruption
    interruption_handler.register_active_response(
        session_id, 
        adapted["adapted_response"],
        {"emotion_context": emotion_result}
    )
    
    # Send to TTS with tone adjustments
    await tts_service.speak(
        text=adapted["adapted_response"],
        tone_adjustments=adapted["tone_adjustments"],
        session_id=session_id
    )
    
    # Unregister when complete
    interruption_handler.unregister_active_response(session_id)
    
    return response
"""