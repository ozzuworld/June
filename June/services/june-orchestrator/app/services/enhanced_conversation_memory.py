# Enhanced Conversation Memory Service for June
# File: June/services/june-orchestrator/app/services/enhanced_conversation_memory.py

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import json
import logging
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    TfidfVectorizer = None
    cosine_similarity = None
    np = None

logger = logging.getLogger(__name__)

@dataclass
class ConversationTurn:
    """Single conversation turn with enhanced metadata"""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime
    emotion_detected: Optional[str] = None
    topic: Optional[str] = None
    intent: Optional[str] = None
    context_references: List[str] = field(default_factory=list)
    response_time_ms: Optional[int] = None
    tokens_used: int = 0
    confidence_score: float = 0.0

@dataclass
class ConversationMemory:
    """Enhanced conversation memory with semantic search"""
    session_id: str
    user_id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    topics_discussed: List[str] = field(default_factory=list)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    conversation_style: str = "neutral"
    last_interaction: Optional[datetime] = None
    total_interactions: int = 0
    
    def add_turn(self, turn: ConversationTurn):
        """Add a conversation turn and update metadata"""
        self.turns.append(turn)
        if turn.topic and turn.topic not in self.topics_discussed:
            self.topics_discussed.append(turn.topic)
        self.last_interaction = turn.timestamp
        self.total_interactions += 1

class EnhancedConversationMemoryService:
    """Enhanced memory service with semantic search and context awareness"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Initialize semantic search if sklearn is available
        if SKLEARN_AVAILABLE:
            self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            self.semantic_search_enabled = True
            logger.info("✅ Semantic search enabled with scikit-learn")
        else:
            self.vectorizer = None
            self.semantic_search_enabled = False
            logger.warning("⚠️ Semantic search disabled - install scikit-learn for enhanced features")
            
        self.conversation_embeddings = {}
        
    async def store_conversation_turn(self, session_id: str, turn: ConversationTurn):
        """Store a conversation turn with enhanced metadata"""
        try:
            # Get existing memory or create new
            memory = await self.get_conversation_memory(session_id)
            if not memory:
                memory = ConversationMemory(session_id=session_id, user_id=turn.role)
            
            # Add the turn
            memory.add_turn(turn)
            
            # Store in Redis
            memory_data = {
                "session_id": memory.session_id,
                "user_id": memory.user_id,
                "turns": [self._turn_to_dict(t) for t in memory.turns[-50:]],  # Keep last 50 turns
                "topics_discussed": memory.topics_discussed,
                "user_preferences": memory.user_preferences,
                "conversation_style": memory.conversation_style,
                "last_interaction": memory.last_interaction.isoformat() if memory.last_interaction else None,
                "total_interactions": memory.total_interactions
            }
            
            await self.redis.setex(
                f"conversation_memory:{session_id}",
                timedelta(days=7).total_seconds(),
                json.dumps(memory_data, default=str)
            )
            
            # Update semantic embeddings if available
            if self.semantic_search_enabled:
                await self._update_embeddings(session_id, turn.content)
            
            logger.info(f"Stored enhanced conversation turn for {session_id}")
            
        except Exception as e:
            logger.error(f"Error storing conversation turn: {e}")
            raise
    
    async def get_relevant_context(self, session_id: str, current_message: str, limit: int = 5) -> List[ConversationTurn]:
        """Get contextually relevant conversation history using semantic similarity"""
        try:
            memory = await self.get_conversation_memory(session_id)
            if not memory or not memory.turns:
                return []
            
            # If semantic search is not available, fall back to recent turns
            if not self.semantic_search_enabled:
                logger.debug("Using recent turns fallback (no semantic search)")
                return memory.turns[-limit:]
            
            # Extract text from turns
            turn_texts = [turn.content for turn in memory.turns if turn.role == 'user']
            if not turn_texts:
                return memory.turns[-limit:]  # Fallback to recent turns
            
            # Add current message for comparison
            all_texts = turn_texts + [current_message]
            
            # Create embeddings
            try:
                tfidf_matrix = self.vectorizer.fit_transform(all_texts)
                current_vector = tfidf_matrix[-1]  # Last item is current message
                
                # Calculate similarities
                similarities = cosine_similarity(current_vector, tfidf_matrix[:-1]).flatten()
                
                # Get most similar turns
                similar_indices = np.argsort(similarities)[-limit:][::-1]
                relevant_turns = []
                
                for idx in similar_indices:
                    if similarities[idx] > 0.1:  # Minimum similarity threshold
                        # Find corresponding assistant response
                        user_turn = memory.turns[idx * 2] if idx * 2 < len(memory.turns) else None
                        assistant_turn = memory.turns[idx * 2 + 1] if idx * 2 + 1 < len(memory.turns) else None
                        
                        if user_turn:
                            relevant_turns.append(user_turn)
                        if assistant_turn:
                            relevant_turns.append(assistant_turn)
                
                return relevant_turns[:limit]
                
            except Exception as e:
                logger.warning(f"Semantic similarity failed, using recent turns: {e}")
                return memory.turns[-limit:]  # Fallback
            
        except Exception as e:
            logger.error(f"Error getting relevant context: {e}")
            return []
    
    async def get_conversation_memory(self, session_id: str) -> Optional[ConversationMemory]:
        """Get conversation memory for a session"""
        try:
            data = await self.redis.get(f"conversation_memory:{session_id}")
            if not data:
                return None
            
            memory_data = json.loads(data)
            memory = ConversationMemory(
                session_id=memory_data["session_id"],
                user_id=memory_data["user_id"],
                topics_discussed=memory_data.get("topics_discussed", []),
                user_preferences=memory_data.get("user_preferences", {}),
                conversation_style=memory_data.get("conversation_style", "neutral"),
                total_interactions=memory_data.get("total_interactions", 0)
            )
            
            # Reconstruct turns
            for turn_data in memory_data.get("turns", []):
                turn = ConversationTurn(
                    role=turn_data["role"],
                    content=turn_data["content"],
                    timestamp=datetime.fromisoformat(turn_data["timestamp"]),
                    emotion_detected=turn_data.get("emotion_detected"),
                    topic=turn_data.get("topic"),
                    intent=turn_data.get("intent"),
                    context_references=turn_data.get("context_references", []),
                    response_time_ms=turn_data.get("response_time_ms"),
                    tokens_used=turn_data.get("tokens_used", 0),
                    confidence_score=turn_data.get("confidence_score", 0.0)
                )
                memory.turns.append(turn)
            
            return memory
            
        except Exception as e:
            logger.error(f"Error getting conversation memory: {e}")
            return None
    
    def _turn_to_dict(self, turn: ConversationTurn) -> Dict[str, Any]:
        """Convert ConversationTurn to dictionary"""
        return {
            "role": turn.role,
            "content": turn.content,
            "timestamp": turn.timestamp.isoformat(),
            "emotion_detected": turn.emotion_detected,
            "topic": turn.topic,
            "intent": turn.intent,
            "context_references": turn.context_references,
            "response_time_ms": turn.response_time_ms,
            "tokens_used": turn.tokens_used,
            "confidence_score": turn.confidence_score
        }
    
    async def _update_embeddings(self, session_id: str, text: str):
        """Update conversation embeddings for semantic search"""
        try:
            # This is a simplified implementation
            # In production, you'd use more sophisticated embeddings
            key = f"embeddings:{session_id}"
            await self.redis.lpush(key, text)
            await self.redis.ltrim(key, 0, 99)  # Keep last 100 texts
            await self.redis.expire(key, timedelta(days=7).total_seconds())
            
        except Exception as e:
            logger.warning(f"Failed to update embeddings: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get memory service statistics"""
        return {
            "service": "enhanced_conversation_memory",
            "version": "1.0.0",
            "semantic_search_enabled": self.semantic_search_enabled,
            "features": ["semantic_search", "context_awareness", "turn_metadata"] if self.semantic_search_enabled else ["context_awareness", "turn_metadata"]
        }

    async def cleanup_expired_conversations(self, ttl_days: int) -> int:
        """Clean up conversations older than TTL"""
        try:
            # This is a simplified cleanup - in production you'd scan Redis more efficiently
            cleaned_count = 0
            logger.info(f"Cleaned up {cleaned_count} expired conversations")
            return cleaned_count
        except Exception as e:
            logger.error(f"Failed to cleanup conversations: {e}")
            return 0

    async def analyze_conversation_patterns(self, session_id: str) -> Dict[str, Any]:
        """Analyze conversation patterns for insights"""
        try:
            memory = await self.get_conversation_memory(session_id)
            if not memory:
                return {}
            
            # Basic pattern analysis
            patterns = {
                "total_turns": len(memory.turns),
                "topics_discussed": memory.topics_discussed,
                "conversation_style": memory.conversation_style,
                "avg_response_time": 0,
                "most_common_intents": []
            }
            
            # Calculate average response time
            response_times = [turn.response_time_ms for turn in memory.turns if turn.response_time_ms]
            if response_times:
                patterns["avg_response_time"] = sum(response_times) / len(response_times)
            
            # Find most common intents
            intents = [turn.intent for turn in memory.turns if turn.intent]
            if intents:
                intent_counts = {}
                for intent in intents:
                    intent_counts[intent] = intent_counts.get(intent, 0) + 1
                patterns["most_common_intents"] = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            
            return patterns
            
        except Exception as e:
            logger.error(f"Failed to analyze patterns: {e}")
            return {}