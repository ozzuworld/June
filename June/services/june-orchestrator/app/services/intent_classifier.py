"""
Intent Classification for June Orchestrator
Phase 1 Implementation

Classifies user intents with confidence scoring.
Supports both rule-based and LLM-based classification.
"""
import logging
import re
from typing import Dict, List, Optional
from .dialogue_state import Intent, ConversationContext

logger = logging.getLogger(__name__)


class IntentClassifier:
    """
    Intent recognition with confidence scoring
    
    Supports:
    - Rule-based matching for known intents
    - Pattern-based classification
    - Context-aware intent detection
    - LLM fallback for complex cases
    """
    
    def __init__(self):
        # Define known intents with trigger phrases
        self.known_intents = {
            # Mockingbird intents
            "mockingbird_enable": {
                "triggers": [
                    "enable mockingbird",
                    "turn on mockingbird",
                    "activate mockingbird",
                    "clone my voice",
                    "use my voice",
                    "speak in my voice",
                    "mimic my voice",
                    "copy my voice"
                ],
                "domain": "voice_control",
                "confidence": 0.95
            },
            "mockingbird_disable": {
                "triggers": [
                    "disable mockingbird",
                    "turn off mockingbird",
                    "deactivate mockingbird",
                    "use your voice",
                    "use your normal voice",
                    "stop using my voice",
                    "use default voice",
                    "switch back to your voice"
                ],
                "domain": "voice_control",
                "confidence": 0.95
            },
            "mockingbird_status": {
                "triggers": [
                    "is mockingbird active",
                    "is mockingbird on",
                    "mockingbird status",
                    "what voice are you using",
                    "are you using my voice",
                    "which voice is active",
                    "what's the current voice"
                ],
                "domain": "voice_control",
                "confidence": 0.90
            },
            
            # Conversational intents
            "greeting": {
                "triggers": [
                    "hello",
                    "hi",
                    "hey",
                    "good morning",
                    "good afternoon",
                    "good evening",
                    "what's up",
                    "howdy",
                    "greetings"
                ],
                "domain": "social",
                "confidence": 0.90
            },
            "farewell": {
                "triggers": [
                    "goodbye",
                    "bye",
                    "see you",
                    "talk to you later",
                    "catch you later",
                    "have a good day",
                    "good night",
                    "take care"
                ],
                "domain": "social",
                "confidence": 0.90
            },
            "help": {
                "triggers": [
                    "help",
                    "what can you do",
                    "how do i",
                    "show me how",
                    "teach me",
                    "explain",
                    "i need help",
                    "can you help me"
                ],
                "domain": "assistance",
                "confidence": 0.85
            },
            "thank_you": {
                "triggers": [
                    "thank you",
                    "thanks",
                    "appreciate it",
                    "much appreciated",
                    "that's helpful",
                    "perfect"
                ],
                "domain": "social",
                "confidence": 0.85
            },
            
            # General catch-all
            "general_question": {
                "triggers": [],  # No specific triggers
                "domain": "general",
                "confidence": 0.5
            }
        }
        
        # Compile regex patterns for faster matching
        self._compile_patterns()
        
        logger.info(f"✅ IntentClassifier initialized with {len(self.known_intents)} intent types")
    
    def _compile_patterns(self):
        """Compile regex patterns for intent triggers"""
        self.patterns = {}
        
        for intent_name, intent_data in self.known_intents.items():
            triggers = intent_data["triggers"]
            if triggers:
                # Create regex pattern from triggers
                pattern = "|".join(re.escape(trigger) for trigger in triggers)
                self.patterns[intent_name] = re.compile(pattern, re.IGNORECASE)
    
    def classify(
        self, 
        text: str, 
        context: Optional[ConversationContext] = None
    ) -> Intent:
        """
        Classify user intent with context awareness
        
        Args:
            text: User input text
            context: Optional conversation context for context-aware classification
            
        Returns:
            Intent object with name, confidence, and slots
        """
        text_lower = text.lower().strip()
        
        # Check for exact pattern matches first
        for intent_name, pattern in self.patterns.items():
            if pattern.search(text_lower):
                intent_data = self.known_intents[intent_name]
                
                logger.info(
                    f"🎯 Intent matched: {intent_name} "
                    f"(confidence: {intent_data['confidence']:.2f})"
                )
                
                return Intent(
                    name=intent_name,
                    confidence=intent_data["confidence"],
                    slots={},
                    domain=intent_data["domain"]
                )
        
        # Check for partial matches with lower confidence
        intent = self._fuzzy_match(text_lower, context)
        if intent:
            return intent
        
        # Context-based classification
        if context:
            intent = self._context_based_classification(text, context)
            if intent:
                return intent
        
        # Default to general question with low confidence
        logger.debug(f"No specific intent matched, defaulting to general_question")
        
        return Intent(
            name="general_question",
            confidence=0.5,
            slots={},
            domain="general"
        )
    
    def _fuzzy_match(
        self, 
        text: str, 
        context: Optional[ConversationContext]
    ) -> Optional[Intent]:
        """
        Fuzzy matching for partial intent matches
        
        Returns intent if partial match found with reasonable confidence
        """
        for intent_name, intent_data in self.known_intents.items():
            triggers = intent_data["triggers"]
            
            for trigger in triggers:
                # Check if any trigger word is in the text
                trigger_words = trigger.split()
                matching_words = sum(1 for word in trigger_words if word in text)
                
                # If more than 50% of trigger words match
                if len(trigger_words) > 0 and matching_words / len(trigger_words) >= 0.5:
                    # Lower confidence for fuzzy match
                    confidence = intent_data["confidence"] * 0.7
                    
                    logger.info(
                        f"🎯 Fuzzy intent match: {intent_name} "
                        f"(confidence: {confidence:.2f})"
                    )
                    
                    return Intent(
                        name=intent_name,
                        confidence=confidence,
                        slots={},
                        domain=intent_data["domain"]
                    )
        
        return None
    
    def _context_based_classification(
        self, 
        text: str, 
        context: ConversationContext
    ) -> Optional[Intent]:
        """
        Use conversation context to infer intent
        
        For example:
        - If last intent was a question, current might be answer
        - If in slot-filling state, might be providing slot value
        """
        # Check if we're in slot-filling mode
        if context.pending_slots:
            # User might be providing a slot value
            return Intent(
                name="slot_filling_response",
                confidence=0.7,
                slots={},
                domain=context.current_intent.domain if context.current_intent else "general"
            )
        
        # Check if this is a follow-up to previous intent
        if context.current_intent and context.total_turns > 0:
            # Might be a clarification or continuation
            recent_turns = context.get_recent_history(max_turns=2)
            if recent_turns and recent_turns[-1]["role"] == "assistant":
                # Last message was from assistant, might be follow-up
                if any(word in text.lower() for word in ["yes", "no", "sure", "okay", "nope"]):
                    return Intent(
                        name="confirmation",
                        confidence=0.75,
                        slots={},
                        domain=context.current_intent.domain
                    )
        
        return None
    
    def classify_batch(
        self, 
        texts: List[str], 
        context: Optional[ConversationContext] = None
    ) -> List[Intent]:
        """
        Classify multiple texts at once
        
        Useful for processing multiple user inputs
        """
        return [self.classify(text, context) for text in texts]
    
    def get_intent_confidence_threshold(self, intent_name: str) -> float:
        """
        Get minimum confidence threshold for an intent
        
        Some intents (like mockingbird) require high confidence
        Others (like general questions) can be lower
        """
        critical_intents = {
            "mockingbird_enable",
            "mockingbird_disable"
        }
        
        return 0.85 if intent_name in critical_intents else 0.60
    
    def is_intent_confident(self, intent: Intent) -> bool:
        """
        Check if intent confidence exceeds its threshold
        """
        threshold = self.get_intent_confidence_threshold(intent.name)
        return intent.confidence >= threshold
    
    def get_available_intents(self) -> List[str]:
        """Get list of all known intent names"""
        return list(self.known_intents.keys())
    
    def get_intent_info(self, intent_name: str) -> Optional[Dict]:
        """Get information about a specific intent"""
        return self.known_intents.get(intent_name)