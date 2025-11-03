# Enhanced Orchestrator Integration for Natural Conversation
# File: June/services/june-orchestrator/app/services/natural_conversation_processor.py

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import json
import re

# Import the enhanced conversation memory components
from .enhanced_conversation_memory import ConversationTurn, EnhancedConversationMemoryService

logger = logging.getLogger(__name__)

class NaturalConversationProcessor:
    """Processes conversations with natural flow and context awareness"""
    
    def __init__(self, enhanced_memory_service: EnhancedConversationMemoryService, ai_service, config):
        self.memory = enhanced_memory_service
        self.ai = ai_service
        self.config = config
        
        # Conversation patterns for natural flow
        self.greeting_patterns = [
            r"^(hi|hello|hey|good morning|good afternoon)\b",
            r"\b(june|assistant|ai)\b"
        ]
        
        self.question_patterns = [
            r"\b(what|how|why|when|where|who)\b",
            r"\?$",
            r"\b(explain|tell me|help me)\b"
        ]
        
        self.continuation_patterns = [
            r"^(and|also|additionally|furthermore|moreover)\b",
            r"\b(continue|go on|tell me more)\b",
            r"^(yes|yeah|right|exactly)\b"
        ]
        
        # Technical vocabulary corrections for your Latin accent
        self.accent_corrections = {
            "square root": ["square root", "скуэр рут", "raíz cuadrada", "skuer root"],
            "algorithm": ["algorithm", "алгоритм", "algoritmo", "algoridm"],
            "function": ["function", "функция", "función", "funccion"],
            "python": ["python", "питон", "pitón", "piton"],
            "kubernetes": ["kubernetes", "кубернетес", "kubernetes", "kubernete"]
        }
    
    async def process_natural_conversation(self, session_id: str, user_message: str, 
                                         audio_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Process conversation with natural flow and context awareness"""
        try:
            start_time = datetime.utcnow()
            
            # Step 1: Apply accent-aware corrections to user message
            corrected_message = self.apply_accent_corrections(user_message)
            if corrected_message != user_message:
                logger.info(f"Applied accent correction: '{user_message}' -> '{corrected_message}'")
            
            # Step 2: Analyze conversation context
            conversation_context = await self.analyze_conversation_context(
                session_id, corrected_message
            )
            
            # Step 3: Determine conversation intent and flow
            intent_info = await self.determine_conversation_intent(
                corrected_message, conversation_context
            )
            
            # Step 4: Get relevant conversation history
            relevant_context = await self.memory.get_relevant_context(
                session_id, corrected_message, limit=5
            )
            
            # Step 5: Build context-aware prompt
            enhanced_prompt = await self.build_context_aware_prompt(
                corrected_message, relevant_context, intent_info, conversation_context
            )
            
            # Step 6: Generate natural response
            ai_response = await self.generate_natural_response(
                enhanced_prompt, intent_info, conversation_context
            )
            
            # Step 7: Store conversation turn
            response_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            user_turn = ConversationTurn(
                role="user",
                content=corrected_message,  # Store corrected version
                timestamp=start_time,
                emotion_detected=audio_context.get("emotion") if audio_context else None,
                topic=intent_info.get("topic"),
                intent=intent_info.get("intent"),
                context_references=[c.content[:50] + "..." for c in relevant_context[:2]],
                response_time_ms=response_time,
                tokens_used=len(corrected_message.split())
            )
            
            assistant_turn = ConversationTurn(
                role="assistant", 
                content=ai_response["content"],
                timestamp=datetime.utcnow(),
                topic=intent_info.get("topic"),
                intent="response",
                tokens_used=ai_response.get("tokens_used", 0),
                confidence_score=ai_response.get("confidence", 0.8)
            )
            
            await self.memory.store_conversation_turn(session_id, user_turn)
            await self.memory.store_conversation_turn(session_id, assistant_turn)
            
            # Step 8: Generate follow-up suggestions
            follow_ups = await self.generate_followup_suggestions(
                corrected_message, ai_response["content"], intent_info
            )
            
            return {
                "response": ai_response["content"],
                "intent": intent_info,
                "context_used": [c.content[:100] for c in relevant_context],
                "follow_up_suggestions": follow_ups,
                "conversation_state": conversation_context.get("state", "active"),
                "topics_discussed": conversation_context.get("topics", []),
                "corrected_input": corrected_message != user_message,
                "original_input": user_message if corrected_message != user_message else None,
                "response_metadata": {
                    "response_time_ms": response_time,
                    "tokens_used": ai_response.get("tokens_used", 0),
                    "confidence": ai_response.get("confidence", 0.8),
                    "context_references": len(relevant_context),
                    "natural_flow": True,
                    "accent_corrected": corrected_message != user_message
                }
            }
            
        except Exception as e:
            logger.error(f"Natural conversation processing failed: {e}")
            raise
    
    def apply_accent_corrections(self, message: str) -> str:
        """Apply corrections for Latin accent transcription issues"""
        try:
            corrected = message
            corrections_applied = []
            
            for correct_term, variations in self.accent_corrections.items():
                for variation in variations[1:]:  # Skip first (correct) term
                    if variation.lower() in corrected.lower():
                        # Case-preserving replacement
                        pattern = re.compile(re.escape(variation), re.IGNORECASE)
                        if pattern.search(corrected):
                            corrected = pattern.sub(correct_term, corrected)
                            corrections_applied.append(f"{variation} -> {correct_term}")
            
            if corrections_applied:
                logger.info(f"Applied accent corrections: {', '.join(corrections_applied)}")
            
            return corrected
            
        except Exception as e:
            logger.warning(f"Accent correction failed: {e}")
            return message
    
    async def analyze_conversation_context(self, session_id: str, message: str) -> Dict[str, Any]:
        """Analyze current conversation context and state"""
        try:
            memory = await self.memory.get_conversation_memory(session_id)
            if not memory:
                return {
                    "state": "new_conversation",
                    "topics": [],
                    "conversation_style": "neutral",
                    "user_preferences": {}
                }
            
            # Determine conversation state
            time_since_last = None
            if memory.last_interaction:
                time_since_last = datetime.utcnow() - memory.last_interaction
            
            if not time_since_last or time_since_last > timedelta(hours=1):
                state = "returning_conversation"
            elif time_since_last > timedelta(minutes=5):
                state = "resumed_conversation" 
            else:
                state = "active_conversation"
            
            # Analyze conversation flow
            recent_turns = memory.turns[-6:] if len(memory.turns) >= 6 else memory.turns
            conversation_flow = self.analyze_conversation_flow(recent_turns, message)
            
            return {
                "state": state,
                "topics": memory.topics_discussed,
                "conversation_style": memory.conversation_style,
                "user_preferences": memory.user_preferences,
                "total_interactions": memory.total_interactions,
                "time_since_last": time_since_last.total_seconds() if time_since_last else None,
                "conversation_flow": conversation_flow
            }
            
        except Exception as e:
            logger.error(f"Context analysis failed: {e}")
            return {"state": "unknown", "topics": [], "conversation_style": "neutral"}
    
    def analyze_conversation_flow(self, recent_turns: List, current_message: str) -> Dict[str, Any]:
        """Analyze conversation flow patterns"""
        try:
            if not recent_turns:
                return {"type": "initiating", "pattern": "greeting"}
            
            last_turn = recent_turns[-1] if recent_turns else None
            
            # Check for greeting patterns
            if any(re.search(pattern, current_message.lower()) for pattern in self.greeting_patterns):
                return {"type": "greeting", "pattern": "social"}
            
            # Check for question patterns  
            if any(re.search(pattern, current_message.lower()) for pattern in self.question_patterns):
                return {"type": "question", "pattern": "information_seeking"}
            
            # Check for continuation patterns
            if any(re.search(pattern, current_message.lower()) for pattern in self.continuation_patterns):
                return {"type": "continuation", "pattern": "elaboration"}
            
            # Check for topic shift
            if last_turn and last_turn.topic:
                current_topic = await self.extract_topic(current_message)
                if current_topic and current_topic != last_turn.topic:
                    return {
                        "type": "topic_shift", 
                        "pattern": "change", 
                        "from_topic": last_turn.topic, 
                        "to_topic": current_topic
                    }
            
            return {"type": "statement", "pattern": "informational"}
            
        except Exception as e:
            logger.warning(f"Flow analysis failed: {e}")
            return {"type": "unknown", "pattern": "default"}
    
    async def determine_conversation_intent(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Determine conversation intent with context awareness"""
        try:
            # Basic intent classification
            message_lower = message.lower()
            
            # Question intents
            if any(word in message_lower for word in ['what', 'how', 'why', 'explain', 'tell me']):
                intent = "question"
                if any(word in message_lower for word in ['math', 'calculate', 'equation', 'number', 'square root']):
                    topic = "mathematics"
                elif any(word in message_lower for word in ['code', 'program', 'function', 'algorithm']):
                    topic = "programming"  
                elif any(word in message_lower for word in ['kubernetes', 'docker', 'deploy']):
                    topic = "devops"
                else:
                    topic = "general"
            
            # Greeting intents
            elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'good morning']):
                intent = "greeting"
                topic = "social"
            
            # Continuation intents
            elif context.get("conversation_flow", {}).get("type") == "continuation":
                intent = "continuation"
                # Use last topic from context
                recent_topics = context.get("topics", [])
                topic = recent_topics[-1] if recent_topics else "general"
            
            # Default
            else:
                intent = "statement"
                topic = await self.extract_topic(message) or "general"
            
            return {
                "intent": intent,
                "topic": topic,
                "confidence": 0.8,  # Could be enhanced with ML model
                "context_aware": True
            }
            
        except Exception as e:
            logger.error(f"Intent determination failed: {e}")
            return {"intent": "unknown", "topic": "general", "confidence": 0.5}
    
    async def extract_topic(self, message: str) -> Optional[str]:
        """Extract topic from message"""
        # Simple keyword-based topic extraction
        # Could be enhanced with NLP models
        message_lower = message.lower()
        
        topic_keywords = {
            "mathematics": ["math", "calculate", "number", "equation", "square root", "algebra"],
            "programming": ["code", "program", "function", "python", "javascript", "algorithm"],
            "devops": ["kubernetes", "docker", "deploy", "container", "pod", "service"],
            "ai": ["ai", "artificial intelligence", "machine learning", "model", "training"],
            "technology": ["tech", "computer", "software", "hardware", "system"]
        }
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                return topic
        
        return None
    
    async def build_context_aware_prompt(self, user_message: str, relevant_context: List,
                                       intent_info: Dict, conversation_context: Dict) -> str:
        """Build enhanced prompt with conversation context"""
        try:
            # Base prompt with personality optimized for your conversational style
            prompt = f"""You are June, a natural and helpful AI assistant with a warm, conversational personality. You engage like a knowledgeable friend who remembers what we've discussed.

Important: The user speaks English with a slight Latino accent, so be understanding and natural in your responses.

Current conversation context:
- Conversation state: {conversation_context.get('state', 'active')}
- Topics we've discussed: {', '.join(conversation_context.get('topics', []))}
- User's current intent: {intent_info.get('intent', 'unknown')}
- Current topic: {intent_info.get('topic', 'general')}"""
            
            # Add relevant conversation history
            if relevant_context:
                prompt += f"\n\nRelevant from our conversation:\n"
                for turn in relevant_context[-3:]:  # Last 3 relevant turns
                    role_emoji = "👤" if turn.role == "user" else "🤖"
                    prompt += f"{role_emoji} {turn.role}: {turn.content}\n"
            
            # Add conversation flow guidance
            flow_type = conversation_context.get('conversation_flow', {}).get('type')
            if flow_type == "greeting":
                prompt += "\n\nThe user is greeting you. Respond warmly and naturally like you're happy to chat."
            elif flow_type == "continuation":
                prompt += "\n\nThe user is continuing our previous discussion. Build on what we talked about."
            elif flow_type == "question":
                prompt += "\n\nThe user has a question. Give a helpful, clear answer that builds on our conversation."
            elif flow_type == "topic_shift":
                prompt += "\n\nThe user is moving to a new topic. Acknowledge the change naturally."
            
            # Special guidance for technical topics (your common use case)
            if intent_info.get("topic") == "mathematics":
                prompt += "\n\nMathematics topic: Be precise with calculations but explain in a friendly, accessible way. Use clear examples."
            elif intent_info.get("topic") == "programming":
                prompt += "\n\nProgramming topic: Provide practical, working examples. Explain concepts clearly."
            elif intent_info.get("topic") == "devops":
                prompt += "\n\nDevOps topic: Focus on practical implementation and best practices."
            
            # Add user preferences if available
            preferences = conversation_context.get('user_preferences', {})
            if preferences:
                prompt += f"\n\nUser preferences: {json.dumps(preferences, indent=2)}"
            
            prompt += f"\n\nUser's message: {user_message}\n\nRespond naturally and conversationally, like we're having a friendly chat:"
            
            return prompt
            
        except Exception as e:
            logger.error(f"Prompt building failed: {e}")
            return f"User: {user_message}\n\nAssistant:"
    
    async def generate_natural_response(self, prompt: str, intent_info: Dict, 
                                      context: Dict) -> Dict[str, Any]:
        """Generate natural AI response with conversation awareness"""
        try:
            # Call your existing AI service with enhanced prompt
            response = await self.ai(prompt, max_tokens=self.config.ai.max_output_tokens)
            
            # Post-process for naturalness
            natural_response = self.enhance_response_naturalness(
                response.get("content", ""), intent_info, context
            )
            
            return {
                "content": natural_response,
                "tokens_used": response.get("usage", {}).get("total_tokens", 0),
                "confidence": 0.8,
                "enhanced": True
            }
            
        except Exception as e:
            logger.error(f"Natural response generation failed: {e}")
            return {
                "content": "I understand what you're asking about. Let me help you with that.",
                "tokens_used": 0,
                "confidence": 0.5,
                "enhanced": False
            }
    
    def enhance_response_naturalness(self, response: str, intent_info: Dict, 
                                   context: Dict) -> str:
        """Post-process response for natural conversation flow"""
        try:
            enhanced = response
            
            # Add natural conversation markers based on intent
            intent = intent_info.get("intent", "unknown")
            
            if intent == "greeting" and context.get("state") == "new_conversation":
                # First time greeting
                if not enhanced.lower().startswith(("hi", "hello", "hey")):
                    enhanced = f"Hi there! {enhanced}"
            
            elif intent == "greeting" and context.get("state") == "returning_conversation":
                # Returning user
                if not enhanced.lower().startswith(("welcome back", "good to see", "hi again")):
                    enhanced = f"Good to see you again! {enhanced}"
            
            elif intent == "continuation":
                # Continuing conversation
                if not enhanced.lower().startswith(("also", "additionally", "furthermore")):
                    enhanced = f"Also, {enhanced.lower()}"
            
            # Remove repetitive phrases that sound robotic
            robotic_phrases = [
                "I'm an AI assistant",
                "As an AI", 
                "I don't have personal experiences",
                "I can't actually",
                "I'm a language model"
            ]
            
            for phrase in robotic_phrases:
                if phrase in enhanced:
                    # Replace with more natural alternatives or remove
                    enhanced = enhanced.replace(phrase, "")
                    enhanced = enhanced.strip()
            
            # Clean up any double spaces or awkward starts
            enhanced = re.sub(r'\s+', ' ', enhanced).strip()
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"Response enhancement failed: {e}")
            return response
    
    async def generate_followup_suggestions(self, user_message: str, ai_response: str,
                                          intent_info: Dict) -> List[str]:
        """Generate natural follow-up suggestions"""
        try:
            topic = intent_info.get("topic", "general")
            intent = intent_info.get("intent", "unknown")
            
            suggestions = []
            
            if topic == "mathematics":
                suggestions = [
                    "Can you show me another example?",
                    "How does this work for different numbers?",
                    "What about more complex calculations?"
                ]
            elif topic == "programming":
                suggestions = [
                    "Can you show this in a different language?",
                    "What are the best practices here?",
                    "Give me a practical example"
                ]
            elif topic == "devops":
                suggestions = [
                    "How does this work in production?",
                    "What about security considerations?",
                    "Show me the configuration"
                ]
            elif intent == "greeting":
                suggestions = [
                    "What can you help me with today?",
                    "Tell me about your capabilities", 
                    "I have a question about..."
                ]
            else:
                suggestions = [
                    "Tell me more about this",
                    "Can you give me an example?",
                    "What else should I know?"
                ]
            
            return suggestions[:3]  # Return max 3 suggestions
            
        except Exception as e:
            logger.warning(f"Follow-up generation failed: {e}")
            return ["Tell me more", "Can you explain further?", "What else?"]

    async def get_conversation_insights(self, session_id: str) -> Dict[str, Any]:
        """Generate insights about the conversation for the user"""
        try:
            patterns = await self.memory.analyze_conversation_patterns(session_id)
            memory = await self.memory.get_conversation_memory(session_id)
            
            if not memory:
                return {"error": "No conversation found"}
            
            insights = {
                "conversation_summary": {
                    "total_exchanges": patterns.get("total_turns", 0) // 2,
                    "topics_covered": patterns.get("topics_discussed", []),
                    "conversation_style": patterns.get("conversation_style", "neutral"),
                    "duration": "active"
                },
                "patterns": {
                    "most_common_topics": patterns.get("topics_discussed", [])[:3],
                    "avg_response_time_ms": patterns.get("avg_response_time", 0),
                    "common_intents": patterns.get("most_common_intents", [])
                },
                "recommendations": [
                    "Continue exploring topics you're interested in",
                    "Feel free to ask follow-up questions", 
                    "I remember our conversation context"
                ]
            }
            
            return insights
            
        except Exception as e:
            logger.error(f"Failed to generate insights: {e}")
            return {"error": "Could not generate insights"}