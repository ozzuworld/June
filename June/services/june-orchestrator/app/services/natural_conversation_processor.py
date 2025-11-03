# Enhanced Orchestrator Integration for Natural Conversation
# File: June/services/june-orchestrator/app/services/natural_conversation_processor.py

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json
import re

from .enhanced_conversation_memory import ConversationTurn, EnhancedConversationMemoryService

logger = logging.getLogger(__name__)

class NaturalConversationProcessor:
    def __init__(self, enhanced_memory_service: EnhancedConversationMemoryService, ai_service, config):
        self.memory = enhanced_memory_service
        self.ai = ai_service
        self.config = config
        self.greeting_patterns = [r"^(hi|hello|hey|good morning|good afternoon)\\b", r"\\b(june|assistant|ai)\\b"]
        self.question_patterns = [r"\\b(what|how|why|when|where|who)\\b", r"\\?$", r"\\b(explain|tell me|help me)\\b"]
        self.continuation_patterns = [r"^(and|also|additionally|furthermore|moreover)\\b", r"\\b(continue|go on|tell me more)\\b", r"^(yes|yeah|right|exactly)\\b"]
        self.accent_corrections = {
            "square root": ["square root", "скуэр рут", "raíz cuadrada", "skuer root"],
            "algorithm": ["algorithm", "алгоритм", "algoritmo", "algoridm"],
            "function": ["function", "функция", "función", "funccion"],
            "python": ["python", "питон", "pitón", "piton"],
            "kubernetes": ["kubernetes", "кубернетес", "kubernetes", "kubernete"],
            "hey june": ["hey june", "Дмитрий", "hey dmitriy", "ey june", "hey you"]
        }

    async def process_natural_conversation(self, session_id: str, user_message: str, audio_context: Optional[Dict] = None) -> Dict[str, Any]:
        start_time = datetime.utcnow()
        corrected_message = self.apply_accent_corrections(user_message)
        conversation_context = await self.analyze_conversation_context(session_id, corrected_message)
        intent_info = await self.determine_conversation_intent(corrected_message, conversation_context)
        relevant_context = await self.memory.get_relevant_context(session_id, corrected_message, limit=5)
        enhanced_prompt = await self.build_context_aware_prompt(corrected_message, relevant_context, intent_info, conversation_context)
        ai_response = await self.generate_natural_response(enhanced_prompt, intent_info, conversation_context)
        response_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        user_turn = ConversationTurn(role="user", content=corrected_message, timestamp=start_time, emotion_detected=audio_context.get("emotion") if audio_context else None, topic=intent_info.get("topic"), intent=intent_info.get("intent"), context_references=[c.content[:50] + "..." for c in relevant_context[:2]], response_time_ms=response_time, tokens_used=len(corrected_message.split()))
        assistant_turn = ConversationTurn(role="assistant", content=ai_response["content"], timestamp=datetime.utcnow(), topic=intent_info.get("topic"), intent="response", tokens_used=ai_response.get("tokens_used", 0), confidence_score=ai_response.get("confidence", 0.8))
        await self.memory.store_conversation_turn(session_id, user_turn)
        await self.memory.store_conversation_turn(session_id, assistant_turn)
        follow_ups = await self.generate_followup_suggestions(corrected_message, ai_response["content"], intent_info)
        return {"response": ai_response["content"], "intent": intent_info, "context_used": [c.content[:100] for c in relevant_context], "follow_up_suggestions": follow_ups, "conversation_state": conversation_context.get("state", "active"), "topics_discussed": conversation_context.get("topics", []), "corrected_input": corrected_message != user_message, "original_input": user_message if corrected_message != user_message else None, "response_metadata": {"response_time_ms": response_time, "tokens_used": ai_response.get("tokens_used", 0), "confidence": ai_response.get("confidence", 0.8), "context_references": len(relevant_context), "natural_flow": True, "accent_corrected": corrected_message != user_message}}

    def apply_accent_corrections(self, message: str) -> str:
        corrected = message
        for correct_term, variations in self.accent_corrections.items():
            for variation in variations[1:]:
                if variation.lower() in corrected.lower():
                    pattern = re.compile(re.escape(variation), re.IGNORECASE)
                    corrected = pattern.sub(correct_term, corrected)
        return corrected

    async def analyze_conversation_context(self, session_id: str, message: str) -> Dict[str, Any]:
        memory = await self.memory.get_conversation_memory(session_id)
        if not memory:
            return {"state": "new_conversation", "topics": [], "conversation_style": "neutral", "user_preferences": {}}
        time_since_last = (datetime.utcnow() - memory.last_interaction) if memory.last_interaction else None
        if not time_since_last or time_since_last > timedelta(hours=1):
            state = "returning_conversation"
        elif time_since_last > timedelta(minutes=5):
            state = "resumed_conversation"
        else:
            state = "active_conversation"
        recent_turns = memory.turns[-6:] if len(memory.turns) >= 6 else memory.turns
        conversation_flow = self.analyze_conversation_flow(recent_turns, message)
        return {"state": state, "topics": memory.topics_discussed, "conversation_style": memory.conversation_style, "user_preferences": memory.user_preferences, "total_interactions": memory.total_interactions, "time_since_last": time_since_last.total_seconds() if time_since_last else None, "conversation_flow": conversation_flow}

    def analyze_conversation_flow(self, recent_turns: List, current_message: str) -> Dict[str, Any]:
        if any(re.search(pattern, current_message.lower()) for pattern in self.greeting_patterns):
            return {"type": "greeting", "pattern": "social"}
        if any(re.search(pattern, current_message.lower()) for pattern in self.question_patterns):
            return {"type": "question", "pattern": "information_seeking"}
        if any(re.search(pattern, current_message.lower()) for pattern in self.continuation_patterns):
            return {"type": "continuation", "pattern": "elaboration"}
        return {"type": "statement", "pattern": "informational"}

    async def determine_conversation_intent(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        msg = message.lower()
        if any(w in msg for w in ['what', 'how', 'why', 'explain', 'tell me']):
            intent = "question"
            if any(w in msg for w in ['math', 'calculate', 'equation', 'number', 'square root']):
                topic = "mathematics"
            elif any(w in msg for w in ['code', 'program', 'function', 'algorithm']):
                topic = "programming"
            elif any(w in msg for w in ['kubernetes', 'docker', 'deploy']):
                topic = "devops"
            else:
                topic = "general"
        elif any(w in msg for w in ['hi', 'hello', 'hey', 'good morning']):
            intent = "greeting"; topic = "social"
        elif context.get("conversation_flow", {}).get("type") == "continuation":
            intent = "continuation"; topic = (context.get("topics", [])[-1] if context.get("topics") else "general")
        else:
            intent = "statement"; topic = await self.extract_topic(message) or "general"
        return {"intent": intent, "topic": topic, "confidence": 0.8, "context_aware": True}

    async def extract_topic(self, message: str) -> Optional[str]:
        msg = message.lower()
        topics = {"mathematics": ["math", "calculate", "number", "equation", "square root", "algebra"], "programming": ["code", "program", "function", "python", "javascript", "algorithm"], "devops": ["kubernetes", "docker", "deploy", "container", "pod", "service"], "ai": ["ai", "artificial intelligence", "machine learning", "model", "training"], "technology": ["tech", "computer", "software", "hardware", "system"]}
        for t, kws in topics.items():
            if any(k in msg for k in kws):
                return t
        return None

    async def build_context_aware_prompt(self, user_message: str, relevant_context: List, intent_info: Dict, conversation_context: Dict) -> str:
        prompt = f"You are June, a natural and helpful AI assistant. The user speaks English with a slight Latino accent.\n\nConversation state: {conversation_context.get('state','active')}\nTopics: {', '.join(conversation_context.get('topics', []))}\nIntent: {intent_info.get('intent','unknown')}\nTopic: {intent_info.get('topic','general')}\n"
        if relevant_context:
            prompt += "\nRelevant conversation history:\n"
            for turn in relevant_context[-3:]:
                role = "User" if turn.role == "user" else "Assistant"
                prompt += f"{role}: {turn.content}\n"
        flow_type = conversation_context.get('conversation_flow', {}).get('type')
        if flow_type == "greeting": prompt += "\nRespond warmly."
        elif flow_type == "continuation": prompt += "\nContinue the previous topic naturally."
        elif flow_type == "question": prompt += "\nAnswer clearly and helpfully."
        elif flow_type == "topic_shift": prompt += "\nAcknowledge the topic change."
        preferences = conversation_context.get('user_preferences', {})
        if preferences: prompt += f"\nUser preferences: {json.dumps(preferences)}"
        prompt += f"\n\nUser's message: {user_message}\nRespond naturally and conversationally:"
        return prompt

    async def generate_natural_response(self, prompt: str, intent_info: Dict, context: Dict) -> Dict[str, Any]:
        response = await self.ai(prompt, max_tokens=self.config.ai.max_output_tokens)
        text = self.enhance_response_naturalness(response.get("content",""), intent_info, context)
        return {"content": text, "tokens_used": response.get("usage", {}).get("total_tokens", 0), "confidence": 0.8, "enhanced": True}

    def enhance_response_naturalness(self, response: str, intent_info: Dict, context: Dict) -> str:
        enhanced = response
        intent = intent_info.get("intent", "unknown")
        if intent == "greeting" and context.get("state") == "new_conversation" and not enhanced.lower().startswith(("hi","hello","hey")):
            enhanced = f"Hi there! {enhanced}"
        elif intent == "greeting" and context.get("state") == "returning_conversation" and not enhanced.lower().startswith(("welcome back","hi again")):
            enhanced = f"Good to see you again! {enhanced}"
        elif intent == "continuation" and not enhanced.lower().startswith(("also","additionally","furthermore")):
            enhanced = f"Also, {enhanced.lower()}"
        for phrase in ["I'm an AI assistant","As an AI","I don't have personal experiences","I'm a language model"]:
            if phrase in enhanced:
                enhanced = enhanced.replace(phrase, "").strip()
        enhanced = re.sub(r"\s+", " ", enhanced).strip()
        return enhanced

    async def generate_followup_suggestions(self, user_message: str, ai_response: str, intent_info: Dict) -> List[str]:
        topic = intent_info.get("topic", "general")
        intent = intent_info.get("intent", "unknown")
        if topic == "mathematics":
            return ["Try another number", "Explain the calculation", "What about negative numbers?"]
        if topic == "programming":
            return ["Show a practical example", "What are best practices?", "In another language?"]
        if topic == "devops":
            return ["Show me the configuration", "Any security considerations?", "How in production?"]
        if intent == "greeting":
            return ["What can you help me with today?", "Tell me your capabilities", "I have a question about..."]
        return ["Tell me more", "Can you give me an example?", "What else should I know?"]
