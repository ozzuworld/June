"""Conversational AI Processor for ChatGPT-style conversation experience"""
import re
import asyncio
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

from .conversation_memory_service import (
    ConversationMemoryService,
    ConversationContext, 
    ConversationState,
    ConversationMessage
)
from .ai_service import generate_response

logger = logging.getLogger(__name__)

@dataclass
class ConversationRequest:
    session_id: str
    user_id: str
    message: str
    audio_data: Optional[str] = None
    context_hint: Optional[str] = None  # For guiding conversation flow

@dataclass 
class ConversationResponse:
    response: str
    conversation_state: str
    context_references: List[str] = None
    followup_suggestions: List[str] = None
    topics_discussed: List[str] = None
    response_metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.context_references is None:
            self.context_references = []
        if self.followup_suggestions is None:
            self.followup_suggestions = []
        if self.topics_discussed is None:
            self.topics_discussed = []
        if self.response_metadata is None:
            self.response_metadata = {}

class ConversationalAIProcessor:
    """Enhanced conversation processor with ChatGPT-style context management"""
    
    def __init__(self, memory_service: ConversationMemoryService, config):
        self.memory = memory_service
        self.config = config
        
        # Intent recognition patterns
        self.intent_patterns = {
            'explanation': r'(explain|what is|how does|tell me about|describe)',
            'elaboration': r'(more about|elaborate|can you expand|tell me more|deeper|further)',
            'implementation': r'(how to implement|show me code|how would I|example|demonstrate)',
            'comparison': r'(compare|difference|vs|versus|better|which)',
            'clarification': r'(clarify|confused|understand|not clear)',
            'follow_up': r'(also|and|what about|related|similar)',
            'exploration': r'(explore|discover|learn|find out)'
        }
        
        # Follow-up suggestion templates
        self.followup_templates = {
            'explanation': [
                "Would you like me to explain {topic} in more detail?",
                "Should I show you how {topic} works in practice?",
                "Want to see some examples of {topic}?"
            ],
            'implementation': [
                "Would you like to see the implementation details?",
                "Should I walk through the code structure?",
                "Want to explore the architecture patterns?"
            ],
            'exploration': [
                "What aspect of {topic} interests you most?",
                "Should we dive deeper into {topic}?",
                "Would you like to explore related concepts?"
            ]
        }
        
    async def process_conversation(self, request: ConversationRequest) -> ConversationResponse:
        """Main conversation processing with enhanced context awareness"""
        start_time = datetime.now()
        
        try:
            # Process audio if provided
            if request.audio_data:
                request.message = await self._process_audio_to_text(request.audio_data)
            
            # Get or create conversation context
            context = await self.memory.get_context(request.session_id)
            if not context:
                context = ConversationContext(
                    session_id=request.session_id,
                    user_id=request.user_id
                )
            
            # Analyze user message
            intent = self._analyze_intent(request.message)
            topics = await self.memory.extract_topics_from_message(request.message)
            
            # Update conversation state and context
            context = await self._update_conversation_state(context, intent, topics, request.message)
            
            # Build conversational context from history
            conversation_context = await self._build_conversational_context(
                context, request.message, intent
            )
            
            # Generate context-aware response using existing AI service
            response = await self._generate_contextual_response(
                request.message, context, conversation_context, intent, request.user_id, request.session_id
            )
            
            # Calculate response time
            response_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Save conversation messages
            await self.memory.add_message(
                request.session_id,
                "user", 
                request.message,
                {
                    "intent": intent,
                    "topics": topics,
                    "timestamp": start_time.isoformat()
                }
            )
            
            await self.memory.add_message(
                request.session_id,
                "assistant",
                response.response,
                {
                    "context_state": context.conversation_state.value,
                    "topics": response.topics_discussed,
                    "response_time_ms": response_time,
                    "context_used": response.context_references
                }
            )
            
            # Update context with latest interaction
            context.last_interaction = datetime.now()
            await self.memory.save_context(context)
            
            response.response_metadata.update({
                "response_time_ms": response_time,
                "intent_detected": intent,
                "context_state": context.conversation_state.value
            })
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing conversation for {request.session_id}: {e}")
            return ConversationResponse(
                response="I apologize, but I encountered an error processing your message. Could you please try again?",
                conversation_state="error",
                response_metadata={"error": str(e)}
            )
    
    def _analyze_intent(self, message: str) -> str:
        """Analyze user message to determine conversational intent"""
        message_lower = message.lower()
        
        # Check patterns in order of specificity
        for intent, pattern in self.intent_patterns.items():
            if re.search(pattern, message_lower):
                return intent
        
        # Check for question patterns
        if message.strip().endswith('?'):
            return 'question'
        
        return 'general'
    
    async def _update_conversation_state(
        self, 
        context: ConversationContext, 
        intent: str, 
        topics: List[str],
        message: str
    ) -> ConversationContext:
        """Update conversation state based on user intent and message"""
        
        # Update conversation state based on intent
        if intent == 'explanation':
            context.conversation_state = ConversationState.EXPLAINING
        elif intent == 'elaboration':
            context.conversation_state = ConversationState.ELABORATING
            context.elaboration_requests.extend(topics)
        elif intent == 'implementation':
            context.conversation_state = ConversationState.IMPLEMENTING
        elif intent in ['exploration', 'follow_up']:
            context.conversation_state = ConversationState.EXPLORING
        else:
            context.conversation_state = ConversationState.LEARNING
        
        # Update topic tracking
        for topic in topics:
            if topic not in context.topic_history:
                context.topic_history.append(topic)
            context.current_topic = topic  # Set most recent topic
        
        # Analyze learning preferences from message patterns
        message_lower = message.lower()
        if any(word in message_lower for word in ['simple', 'basic', 'beginner']):
            context.understanding_level = "beginner"
        elif any(word in message_lower for word in ['advanced', 'expert', 'deep', 'complex']):
            context.understanding_level = "advanced"
        elif any(word in message_lower for word in ['code', 'implementation', 'example']):
            context.learning_preferences["example_preference"] = "code_heavy"
        elif any(word in message_lower for word in ['theory', 'concept', 'principle']):
            context.learning_preferences["example_preference"] = "theory_focused"
        
        return context
    
    async def _build_conversational_context(
        self,
        context: ConversationContext,
        current_message: str,
        intent: str
    ) -> Dict[str, Any]:
        """Build rich conversational context from history and current state"""
        
        # Get recent conversation history
        recent_history = await self.memory.get_conversation_history(context.session_id, 10)
        
        # Get topic-specific context if we have a current topic
        topic_context = []
        if context.current_topic:
            topic_context = await self.memory.get_topic_context(
                context.session_id, context.current_topic, 5
            )
        
        # Analyze conversation patterns for better understanding
        patterns = await self.memory.analyze_conversation_patterns(context.session_id)
        
        return {
            "recent_history": recent_history,
            "topic_context": topic_context,
            "conversation_patterns": patterns,
            "current_state": context.conversation_state.value,
            "understanding_level": context.understanding_level,
            "learning_preferences": context.learning_preferences,
            "topic_history": context.topic_history[-5:],  # Last 5 topics
            "elaboration_requests": context.elaboration_requests[-3:],  # Last 3 elaborations
            "session_duration": (datetime.now() - (recent_history[0].timestamp if recent_history else datetime.now())).total_seconds() / 3600
        }
    
    async def _generate_contextual_response(
        self,
        message: str,
        context: ConversationContext,
        conversation_context: Dict[str, Any],
        intent: str,
        user_id: str,
        session_id: str
    ) -> ConversationResponse:
        """Generate response using conversational context and existing AI service"""
        
        # Build enhanced conversation history for existing AI service
        enhanced_history = self._build_enhanced_history(conversation_context, intent, context)
        
        # Generate response using existing AI service with enhanced context
        try:
            response_text, response_time = await generate_response(
                text=message,
                user_id=user_id,
                session_id=session_id,
                conversation_history=enhanced_history
            )
        except Exception as e:
            logger.error(f"AI service error: {e}")
            response_text = self._generate_fallback_response(message, intent)
            response_time = 0
        
        # Generate contextual follow-up suggestions
        followups = self._generate_contextual_followups(context, intent)
        
        # Extract context references from the conversation
        references = self._extract_context_references(conversation_context, message)
        
        # Identify topics discussed in response
        response_topics = await self.memory.extract_topics_from_message(response_text)
        
        return ConversationResponse(
            response=response_text,
            conversation_state=context.conversation_state.value,
            context_references=references,
            followup_suggestions=followups,
            topics_discussed=response_topics,
            response_metadata={"ai_response_time_ms": response_time}
        )
    
    def _build_enhanced_history(self, conversation_context: Dict[str, Any], intent: str, context: ConversationContext) -> List[Dict]:
        """Build enhanced conversation history with context information"""
        history = []
        
        # Add context primer based on conversation state
        context_primer = f"""[Context: This is a {context.conversation_state.value} conversation. 
User prefers {context.understanding_level} level explanations. 
Current topic: {context.current_topic or 'general'}. 
Intent: {intent}]"""
        
        history.append({
            "role": "system",
            "content": context_primer
        })
        
        # Add recent conversation history
        recent_history = conversation_context.get("recent_history", [])
        for msg in recent_history[-10:]:  # Last 10 messages
            history.append({
                "role": msg.role,
                "content": msg.content
            })
        
        return history
    
    def _generate_fallback_response(self, message: str, intent: str) -> str:
        """Generate a fallback response when AI service is unavailable"""
        fallbacks = {
            'explanation': "I'd be happy to explain that concept! However, I'm experiencing a temporary issue with my processing. Could you please try again in a moment?",
            'elaboration': "I can definitely elaborate on that topic! I'm having a brief technical issue, but please ask again and I'll provide more details.",
            'implementation': "I can help with implementation details! I'm currently experiencing a temporary issue, but please try your question again.",
            'comparison': "That's a great comparison question! I'm having a brief technical difficulty, but please ask again for a detailed comparison."
        }
        
        return fallbacks.get(intent, 
            "I understand your question and would love to help! I'm experiencing a brief technical issue. Please try asking again in a moment.")
    
    def _generate_contextual_followups(
        self, 
        context: ConversationContext, 
        intent: str
    ) -> List[str]:
        """Generate contextual follow-up suggestions"""
        followups = []
        
        # Get appropriate templates
        templates = self.followup_templates.get(intent, self.followup_templates['exploration'])
        
        try:
            # Use current topic for personalized suggestions
            if context.current_topic:
                topic = context.current_topic
                for template in templates[:2]:  # Take first 2 templates
                    followups.append(template.format(topic=topic))
            
            # Add state-specific suggestions
            if context.conversation_state == ConversationState.LEARNING:
                followups.append("What would you like to explore next?")
            elif context.conversation_state == ConversationState.IMPLEMENTING:
                followups.append("Should we look at any specific implementation patterns?")
            elif context.conversation_state == ConversationState.ELABORATING:
                followups.append("Would you like me to dive even deeper into this topic?")
            
            # Add topic-transition suggestions based on history
            if len(context.topic_history) > 1:
                prev_topic = context.topic_history[-2] if len(context.topic_history) > 1 else None
                if prev_topic and prev_topic != context.current_topic:
                    followups.append(f"How does this relate to {prev_topic} that we discussed earlier?")
        
        except Exception as e:
            logger.warning(f"Error generating followups: {e}")
            followups = ["What would you like to know more about?"]
        
        return followups[:3]  # Return max 3 suggestions
    
    def _extract_context_references(
        self, 
        conversation_context: Dict[str, Any], 
        current_message: str
    ) -> List[str]:
        """Extract references to previous context used in the response"""
        references = []
        
        try:
            # Check if we used recent history
            if conversation_context.get("recent_history"):
                references.append("recent conversation")
            
            # Check if we used topic context
            if conversation_context.get("topic_context"):
                references.append(f"previous {conversation_context.get('current_topic', 'topic')} discussion")
            
            # Check if we used elaboration context
            if conversation_context.get("elaboration_requests"):
                references.append("elaboration history")
            
            # Check if we used learning preferences
            if conversation_context.get("learning_preferences"):
                references.append("learning preferences")
                
        except Exception as e:
            logger.warning(f"Error extracting context references: {e}")
            
        return references
    
    async def _process_audio_to_text(self, audio_data: str) -> str:
        """Process audio through STT service if needed"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.config.services.stt_base_url}/transcribe",
                    json={"audio": audio_data}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("text", "")
                else:
                    logger.error(f"STT service error: {response.status_code}")
                    return "[Audio transcription failed]"
                    
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return "[Audio processing error]"
    
    async def get_conversation_insights(self, session_id: str) -> Dict[str, Any]:
        """Get insights about the conversation for debugging/analytics"""
        try:
            context = await self.memory.get_context(session_id)
            patterns = await self.memory.analyze_conversation_patterns(session_id)
            summary = await self.memory.get_conversation_summary(session_id)
            
            return {
                "context": {
                    "current_state": context.conversation_state.value if context else None,
                    "current_topic": context.current_topic if context else None,
                    "understanding_level": context.understanding_level if context else None,
                    "topic_history": context.topic_history if context else [],
                    "elaboration_requests": context.elaboration_requests if context else []
                },
                "patterns": patterns,
                "summary": summary,
                "memory_stats": self.memory.get_stats()
            }
        except Exception as e:
            logger.error(f"Error getting conversation insights: {e}")
            return {"error": str(e)}