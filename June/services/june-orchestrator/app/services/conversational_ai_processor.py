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
            
            # Generate context-aware response
            response = await self._generate_contextual_response(
                request.message, context, conversation_context, intent
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
        intent: str
    ) -> ConversationResponse:
        """Generate response using conversational context"""
        
        # Build context-aware prompt
        prompt = self._build_conversational_prompt(
            message, context, conversation_context, intent
        )
        
        # Generate response using AI service
        try:
            response_text = await self._call_ai_service(prompt)
        except Exception as e:
            logger.error(f"AI service error: {e}")
            response_text = self._generate_fallback_response(message, intent)
        
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
            topics_discussed=response_topics
        )
    
    def _build_conversational_prompt(
        self,
        message: str,
        context: ConversationContext,
        conversation_context: Dict[str, Any],
        intent: str
    ) -> str:
        """Build comprehensive context-aware prompt for AI"""
        
        prompt_parts = [
            "You are June, a conversational AI assistant specialized in technology concepts and learning.",
            "You maintain context across conversations and build naturally on previous discussions.",
            "",
            f"CONVERSATION STATE: {context.conversation_state.value}",
            f"USER'S LEARNING LEVEL: {context.understanding_level}",
            f"LEARNING PREFERENCES: {context.learning_preferences}",
        ]
        
        # Add conversation history context
        if conversation_context.get("recent_history"):
            prompt_parts.append("\nRECENT CONVERSATION:")
            for msg in conversation_context["recent_history"][-3:]:  # Last 3 messages
                role_label = "You" if msg.role == "assistant" else "User"
                content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
                prompt_parts.append(f"{role_label}: {content}")
        
        # Add topic context if relevant
        if context.current_topic and conversation_context.get("topic_context"):
            prompt_parts.append(f"\nPREVIOUS DISCUSSION ABOUT '{context.current_topic.upper()}'S:")
            for msg in conversation_context["topic_context"][-2:]:
                role_label = "You" if msg.role == "assistant" else "User"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                prompt_parts.append(f"{role_label}: {content}")
        
        # Add topics we've been exploring
        if context.topic_history:
            recent_topics = ", ".join(context.topic_history[-5:])
            prompt_parts.append(f"\nTOPICS WE'VE DISCUSSED: {recent_topics}")
        
        # Add elaboration context
        if context.elaboration_requests:
            elaborations = ", ".join(context.elaboration_requests[-3:])
            prompt_parts.append(f"\nTOPICS YOU'VE ELABORATED ON: {elaborations}")
        
        # Intent-specific guidance
        if intent == 'elaboration':
            prompt_parts.append("\nINSTRUCTION: The user is asking for elaboration. Build upon previous explanations with deeper insights, examples, or different perspectives. Reference what we've already discussed.")
        elif intent == 'explanation':
            prompt_parts.append(f"\nINSTRUCTION: Provide a clear explanation suitable for {context.understanding_level} level. Use examples that match their learning preferences.")
        elif intent == 'implementation':
            prompt_parts.append("\nINSTRUCTION: Focus on practical implementation. Provide code examples, architecture patterns, or step-by-step guidance.")
        elif intent == 'comparison':
            prompt_parts.append("\nINSTRUCTION: Provide a thorough comparison. Reference any related concepts we've discussed before.")
        elif intent == 'clarification':
            prompt_parts.append("\nINSTRUCTION: Clarify the concept by building on our previous discussion. Use simpler terms or different analogies.")
        elif intent == 'follow_up':
            prompt_parts.append("\nINSTRUCTION: This is a follow-up question. Connect it naturally to our ongoing conversation thread.")
        
        # Add conversation patterns context
        patterns = conversation_context.get("conversation_patterns", {})
        if patterns.get("elaboration_requests", 0) > 2:
            prompt_parts.append("\nNOTE: The user frequently asks for elaboration - they appreciate detailed, comprehensive explanations.")
        if patterns.get("implementation_requests", 0) > 1:
            prompt_parts.append("\nNOTE: The user is interested in practical implementation - include code examples when relevant.")
        
        prompt_parts.extend([
            f"\nCURRENT USER MESSAGE: {message}",
            "",
            "RESPONSE GUIDELINES:",
            "- Reference our previous conversation naturally when relevant",
            "- Build upon concepts we've already established",
            "- Match the user's learning level and preferences",
            "- Be conversational and engaging",
            "- Provide practical examples for technical concepts",
            "- Suggest natural follow-ups or deeper exploration",
            "- If elaborating, add new insights rather than repeating"
        ])
        
        return "\n".join(prompt_parts)
    
    async def _call_ai_service(self, prompt: str) -> str:
        """Call AI service with the conversational prompt"""
        try:
            # Use your existing AI service integration
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Adjust this URL to match your actual AI service
                response = await client.post(
                    f"{self.config.services.gemini_api_url or 'http://localhost:8000'}/generate",
                    json={
                        "prompt": prompt,
                        "max_tokens": self.config.ai.max_output_tokens or 1000,
                        "temperature": 0.7,
                        "model": self.config.ai.model or "gemini-pro"
                    },
                    headers={
                        "Authorization": f"Bearer {self.config.services.gemini_api_key}"
                    } if self.config.services.gemini_api_key else {}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", result.get("text", "I apologize, but I couldn't generate a response."))
                else:
                    logger.error(f"AI service returned status {response.status_code}: {response.text}")
                    raise Exception(f"AI service error: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Error calling AI service: {e}")
            raise
    
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
