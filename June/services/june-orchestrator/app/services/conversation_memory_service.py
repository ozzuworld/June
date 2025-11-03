"""Conversation Memory Service for ChatGPT-style conversational experience"""
import redis.asyncio as redis
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ConversationState(Enum):
    LEARNING = "learning"
    EXPLAINING = "explaining" 
    ELABORATING = "elaborating"
    IMPLEMENTING = "implementing"
    EXPLORING = "exploring"

@dataclass
class ConversationContext:
    session_id: str
    user_id: str
    current_topic: Optional[str] = None
    conversation_state: ConversationState = ConversationState.LEARNING
    topic_history: List[str] = None
    understanding_level: str = "intermediate"  # beginner, intermediate, advanced
    last_interaction: datetime = None
    elaboration_requests: List[str] = None
    learning_preferences: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.topic_history is None:
            self.topic_history = []
        if self.elaboration_requests is None:
            self.elaboration_requests = []
        if self.last_interaction is None:
            self.last_interaction = datetime.now()
        if self.learning_preferences is None:
            self.learning_preferences = {
                "detail_level": "comprehensive",
                "example_preference": "code_heavy",
                "follow_up_style": "proactive"
            }

@dataclass
class ConversationMessage:
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    intent: Optional[str] = None
    topic: Optional[str] = None
    context_used: List[str] = None
    tokens_used: int = 0
    response_time_ms: int = 0
    
    def __post_init__(self):
        if self.context_used is None:
            self.context_used = []

class ConversationMemoryService:
    """Enhanced memory service for conversational AI experience"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.context_ttl = 86400 * 7  # 7 days
        self.history_ttl = 86400 * 30  # 30 days
        self.summary_ttl = 86400 * 90  # 90 days for summaries
        
        # Tech keywords for topic extraction
        self.tech_keywords = {
            'infrastructure': ['kubernetes', 'docker', 'k8s', 'container', 'deployment', 'helm'],
            'ai_ml': ['ai', 'ml', 'llm', 'model', 'training', 'inference', 'neural', 'gpt'],
            'networking': ['api', 'rest', 'graphql', 'websocket', 'tcp', 'http', 'ssl', 'tls'],
            'voice_tech': ['tts', 'stt', 'voice', 'audio', 'speech', 'livekit', 'webrtc'],
            'databases': ['redis', 'postgres', 'mongodb', 'sql', 'nosql', 'cache'],
            'security': ['auth', 'jwt', 'oauth', 'keycloak', 'security', 'encryption'],
            'architecture': ['microservices', 'monolith', 'serverless', 'event-driven', 'patterns'],
            'devops': ['ci/cd', 'github', 'actions', 'monitoring', 'logging', 'metrics']
        }
        
    async def get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Retrieve conversation context from Redis"""
        try:
            key = f"conversation:context:{session_id}"
            data = await self.redis.get(key)
            
            if not data:
                return None
                
            context_dict = json.loads(data)
            # Convert ISO string back to datetime
            context_dict['last_interaction'] = datetime.fromisoformat(context_dict['last_interaction'])
            context_dict['conversation_state'] = ConversationState(context_dict['conversation_state'])
            
            return ConversationContext(**context_dict)
        except Exception as e:
            logger.error(f"Error retrieving context for {session_id}: {e}")
            return None
    
    async def save_context(self, context: ConversationContext):
        """Save conversation context to Redis"""
        try:
            key = f"conversation:context:{context.session_id}"
            context_dict = asdict(context)
            context_dict['last_interaction'] = context.last_interaction.isoformat()
            context_dict['conversation_state'] = context.conversation_state.value
            
            await self.redis.setex(
                key, 
                self.context_ttl, 
                json.dumps(context_dict, default=str)
            )
        except Exception as e:
            logger.error(f"Error saving context for {context.session_id}: {e}")
    
    async def add_message(
        self, 
        session_id: str, 
        role: str, 
        content: str, 
        metadata: Dict = None
    ):
        """Add message to conversation history"""
        try:
            key = f"conversation:history:{session_id}"
            
            message = ConversationMessage(
                role=role,
                content=content,
                timestamp=datetime.now(),
                intent=metadata.get('intent') if metadata else None,
                topic=metadata.get('topic') if metadata else None,
                context_used=metadata.get('context_used', []) if metadata else [],
                tokens_used=metadata.get('tokens_used', 0) if metadata else 0,
                response_time_ms=metadata.get('response_time_ms', 0) if metadata else 0
            )
            
            message_dict = asdict(message)
            message_dict['timestamp'] = message.timestamp.isoformat()
            
            # Use Redis list to maintain order
            await self.redis.lpush(key, json.dumps(message_dict))
            await self.redis.expire(key, self.history_ttl)
            
            # Keep only last 200 messages per session
            await self.redis.ltrim(key, 0, 199)
        except Exception as e:
            logger.error(f"Error adding message to {session_id}: {e}")
    
    async def get_conversation_history(self, session_id: str, limit: int = 20) -> List[ConversationMessage]:
        """Retrieve conversation history"""
        try:
            key = f"conversation:history:{session_id}"
            messages_data = await self.redis.lrange(key, 0, limit - 1)
            
            messages = []
            for msg_data in reversed(messages_data):  # Reverse to get chronological order
                try:
                    msg_dict = json.loads(msg_data)
                    msg_dict['timestamp'] = datetime.fromisoformat(msg_dict['timestamp'])
                    messages.append(ConversationMessage(**msg_dict))
                except Exception as e:
                    logger.warning(f"Error parsing message in {session_id}: {e}")
                    continue
            
            return messages
        except Exception as e:
            logger.error(f"Error retrieving history for {session_id}: {e}")
            return []
    
    async def get_topic_context(self, session_id: str, topic: str, limit: int = 10) -> List[ConversationMessage]:
        """Get messages related to a specific topic"""
        try:
            # Get more messages to search through
            history = await self.get_conversation_history(session_id, 50)
            topic_messages = []
            
            topic_lower = topic.lower()
            for msg in history:
                # Check if topic is mentioned in content or metadata
                if (topic_lower in msg.content.lower() or 
                    (msg.topic and topic_lower in msg.topic.lower())):
                    topic_messages.append(msg)
                    if len(topic_messages) >= limit:
                        break
            
            return topic_messages
        except Exception as e:
            logger.error(f"Error retrieving topic context for {session_id}, topic {topic}: {e}")
            return []
    
    async def extract_topics_from_message(self, message: str) -> List[str]:
        """Extract technology topics from a message"""
        message_lower = message.lower()
        found_topics = []
        
        for category, keywords in self.tech_keywords.items():
            for keyword in keywords:
                if keyword in message_lower:
                    found_topics.append(keyword)
        
        return list(set(found_topics))  # Remove duplicates
    
    async def analyze_conversation_patterns(self, session_id: str) -> Dict[str, Any]:
        """Analyze conversation patterns for better context understanding"""
        try:
            history = await self.get_conversation_history(session_id, 50)
            
            if not history:
                return {}
            
            # Analyze patterns
            user_messages = [msg for msg in history if msg.role == "user"]
            assistant_messages = [msg for msg in history if msg.role == "assistant"]
            
            # Question patterns
            questions = [msg for msg in user_messages if any(q in msg.content.lower() for q in 
                        ['what', 'how', 'why', 'explain', 'tell me', 'can you'])]
            
            elaboration_requests = [msg for msg in user_messages if any(e in msg.content.lower() for e in 
                                  ['more about', 'elaborate', 'expand', 'tell me more', 'deeper'])]
            
            implementation_requests = [msg for msg in user_messages if any(i in msg.content.lower() for i in 
                                     ['implement', 'code', 'example', 'how to', 'show me'])]
            
            # Topic frequency
            all_topics = []
            for msg in history:
                if msg.topic:
                    all_topics.append(msg.topic)
            
            topic_frequency = {}
            for topic in all_topics:
                topic_frequency[topic] = topic_frequency.get(topic, 0) + 1
            
            return {
                "total_messages": len(history),
                "user_messages": len(user_messages),
                "assistant_messages": len(assistant_messages),
                "questions_asked": len(questions),
                "elaboration_requests": len(elaboration_requests),
                "implementation_requests": len(implementation_requests),
                "topic_frequency": topic_frequency,
                "avg_message_length": sum(len(msg.content) for msg in user_messages) / len(user_messages) if user_messages else 0,
                "conversation_duration_hours": (history[-1].timestamp - history[0].timestamp).total_seconds() / 3600 if len(history) > 1 else 0
            }
        except Exception as e:
            logger.error(f"Error analyzing patterns for {session_id}: {e}")
            return {}
    
    async def create_conversation_summary(self, session_id: str) -> Optional[str]:
        """Create a summary of the conversation for long-term memory"""
        try:
            history = await self.get_conversation_history(session_id, 100)
            if len(history) < 5:  # Don't summarize short conversations
                return None
            
            # Extract key information
            topics = set()
            key_exchanges = []
            
            for i, msg in enumerate(history):
                if msg.topic:
                    topics.add(msg.topic)
                
                # Identify key exchanges (question-answer pairs)
                if (msg.role == "user" and 
                    any(q in msg.content.lower() for q in ['what', 'how', 'explain']) and
                    i + 1 < len(history) and history[i + 1].role == "assistant"):
                    
                    key_exchanges.append({
                        "question": msg.content[:200],
                        "answer": history[i + 1].content[:300],
                        "timestamp": msg.timestamp.isoformat()
                    })
            
            summary = {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "message_count": len(history),
                "duration_hours": (history[-1].timestamp - history[0].timestamp).total_seconds() / 3600 if len(history) > 1 else 0,
                "topics_discussed": list(topics),
                "key_exchanges": key_exchanges[-10:],  # Last 10 key exchanges
                "conversation_type": "technical_learning" if any(t in topics for t in 
                                    ['ai', 'kubernetes', 'docker', 'api', 'programming']) else "general"
            }
            
            # Store summary
            summary_key = f"conversation:summary:{session_id}"
            await self.redis.setex(summary_key, self.summary_ttl, json.dumps(summary))
            
            return json.dumps(summary, indent=2)
        except Exception as e:
            logger.error(f"Error creating summary for {session_id}: {e}")
            return None
    
    async def get_conversation_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve conversation summary"""
        try:
            summary_key = f"conversation:summary:{session_id}"
            data = await self.redis.get(summary_key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving summary for {session_id}: {e}")
            return None
    
    async def cleanup_expired_conversations(self, days_old: int = 30) -> int:
        """Clean up old conversation data"""
        try:
            cutoff_time = datetime.now() - timedelta(days=days_old)
            cleaned = 0
            
            # This is a simplified cleanup - in production you'd want more sophisticated cleanup
            # For now, Redis TTL handles most cleanup automatically
            
            logger.info(f"Conversation cleanup completed: {cleaned} sessions cleaned")
            return cleaned
        except Exception as e:
            logger.error(f"Error during conversation cleanup: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory service statistics (sync method for backward compatibility)"""
        try:
            # For sync compatibility, we'll return basic stats
            # In a production system, you might want to make this async
            return {
                "service": "conversation_memory",
                "backend": "redis",
                "context_ttl_days": self.context_ttl // 86400,
                "history_ttl_days": self.history_ttl // 86400,
                "summary_ttl_days": self.summary_ttl // 86400,
                "tech_categories": len(self.tech_keywords),
                "total_keywords": sum(len(keywords) for keywords in self.tech_keywords.values())
            }
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return {"error": str(e)}