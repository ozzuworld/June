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
        
        if SKLEARN_AVAILABLE:
            self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            self.semantic_search_enabled = True
        else:
            self.vectorizer = None
            self.semantic_search_enabled = False
            logger.warning("Semantic search disabled - install scikit-learn")
        
    async def store_conversation_turn(self, session_id: str, turn: ConversationTurn):
        memory = await self.get_conversation_memory(session_id)
        if not memory:
            memory = ConversationMemory(session_id=session_id, user_id=turn.role)
        memory.add_turn(turn)
        memory_data = {
            "session_id": memory.session_id,
            "user_id": memory.user_id,
            "turns": [self._turn_to_dict(t) for t in memory.turns[-50:]],
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
        if self.semantic_search_enabled:
            await self._update_embeddings(session_id, turn.content)
    
    async def get_relevant_context(self, session_id: str, current_message: str, limit: int = 5) -> List[ConversationTurn]:
        memory = await self.get_conversation_memory(session_id)
        if not memory or not memory.turns:
            return []
        if not self.semantic_search_enabled:
            return memory.turns[-limit:]
        turn_texts = [turn.content for turn in memory.turns if turn.role == 'user']
        if not turn_texts:
            return memory.turns[-limit:]
        all_texts = turn_texts + [current_message]
        try:
            tfidf_matrix = self.vectorizer.fit_transform(all_texts)
            current_vector = tfidf_matrix[-1]
            similarities = cosine_similarity(current_vector, tfidf_matrix[:-1]).flatten()
            similar_indices = np.argsort(similarities)[-limit:][::-1]
            relevant_turns = []
            for idx in similar_indices:
                if similarities[idx] > 0.1:
                    user_turn = memory.turns[idx * 2] if idx * 2 < len(memory.turns) else None
                    assistant_turn = memory.turns[idx * 2 + 1] if idx * 2 + 1 < len(memory.turns) else None
                    if user_turn:
                        relevant_turns.append(user_turn)
                    if assistant_turn:
                        relevant_turns.append(assistant_turn)
            return relevant_turns[:limit]
        except Exception:
            return memory.turns[-limit:]
    
    async def get_conversation_memory(self, session_id: str) -> Optional[ConversationMemory]:
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
    
    def _turn_to_dict(self, turn: ConversationTurn) -> Dict[str, Any]:
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
        key = f"embeddings:{session_id}"
        await self.redis.lpush(key, text)
        await self.redis.ltrim(key, 0, 99)
        await self.redis.expire(key, timedelta(days=7).total_seconds())

    def get_stats(self) -> Dict[str, Any]:
        return {
            "service": "enhanced_conversation_memory",
            "version": "1.0.0",
            "semantic_search_enabled": self.semantic_search_enabled
        }
