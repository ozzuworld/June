"""
Slot Extraction for June Orchestrator
Phase 1 Implementation

Extracts entities and parameters from user text based on intent.
Supports named entity recognition and pattern-based extraction.
"""
import logging
import re
from typing import Dict, List, Optional, Any
from .dialogue_state import Intent

logger = logging.getLogger(__name__)


class SlotExtractor:
    """
    Extract entities and slot values from text
    
    Supports:
    - Named entity recognition (basic)
    - Pattern-based extraction
    - Intent-specific slot extraction
    - Validation of extracted values
    """
    
    def __init__(self):
        # Define slots for each intent
        self.intent_slots = {
            "mockingbird_enable": {
                "required": [],
                "optional": ["voice_gender", "voice_style"]
            },
            "mockingbird_disable": {
                "required": [],
                "optional": []
            },
            "mockingbird_status": {
                "required": [],
                "optional": []
            }
        }
        
        # Slot extraction patterns
        self.patterns = {
            "voice_gender": re.compile(r'\b(male|female|neutral)\b', re.IGNORECASE),
            "voice_style": re.compile(r'\b(professional|casual|friendly|energetic|calm)\b', re.IGNORECASE),
            "duration": re.compile(r'(\d+)\s*(second|minute|hour)s?', re.IGNORECASE),
            "number": re.compile(r'\b(\d+)\b'),
            "yes_no": re.compile(r'\b(yes|no|yeah|nope|sure|okay|ok)\b', re.IGNORECASE)
        }
        
        logger.info("✅ SlotExtractor initialized")
    
    def extract(
        self, 
        text: str, 
        intent: Intent,
        existing_slots: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extract slots based on intent
        
        Args:
            text: User input text
            intent: Detected intent
            existing_slots: Previously filled slots (for context)
            
        Returns:
            Dictionary of extracted slot values
        """
        extracted = {}
        
        # Get intent-specific slots
        intent_config = self.intent_slots.get(intent.name, {})
        required_slots = intent_config.get("required", [])
        optional_slots = intent_config.get("optional", [])
        
        # Extract each slot type
        all_slots = required_slots + optional_slots
        
        for slot_name in all_slots:
            value = self._extract_slot_value(slot_name, text)
            if value is not None:
                extracted[slot_name] = value
                logger.debug(f"Extracted slot: {slot_name}={value}")
        
        # Intent-specific extraction
        if intent.name.startswith("mockingbird"):
            extracted.update(self._extract_mockingbird_slots(text))
        
        return extracted
    
    def _extract_slot_value(self, slot_name: str, text: str) -> Optional[Any]:
        """
        Extract a specific slot value from text
        
        Uses pattern matching or custom extraction logic
        """
        # Check if we have a pattern for this slot
        if slot_name in self.patterns:
            match = self.patterns[slot_name].search(text)
            if match:
                return match.group(1).lower()
        
        # Custom extraction logic for specific slots
        if slot_name == "voice_gender":
            return self._extract_voice_gender(text)
        elif slot_name == "voice_style":
            return self._extract_voice_style(text)
        elif slot_name == "duration":
            return self._extract_duration(text)
        
        return None
    
    def _extract_voice_gender(self, text: str) -> Optional[str]:
        """Extract voice gender preference"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["male", "man's", "masculine"]):
            return "male"
        elif any(word in text_lower for word in ["female", "woman's", "feminine"]):
            return "female"
        elif "neutral" in text_lower:
            return "neutral"
        
        return None
    
    def _extract_voice_style(self, text: str) -> Optional[str]:
        """Extract voice style preference"""
        text_lower = text.lower()
        
        styles = {
            "professional": ["professional", "business", "formal"],
            "casual": ["casual", "relaxed", "laid back"],
            "friendly": ["friendly", "warm", "welcoming"],
            "energetic": ["energetic", "excited", "upbeat"],
            "calm": ["calm", "soothing", "peaceful"]
        }
        
        for style, keywords in styles.items():
            if any(keyword in text_lower for keyword in keywords):
                return style
        
        return None
    
    def _extract_duration(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract duration from text
        
        Returns dict with value and unit
        """
        match = self.patterns["duration"].search(text)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            
            # Normalize to seconds
            if unit.startswith("minute"):
                seconds = value * 60
            elif unit.startswith("hour"):
                seconds = value * 3600
            else:
                seconds = value
            
            return {
                "value": value,
                "unit": unit,
                "seconds": seconds
            }
        
        return None
    
    def _extract_mockingbird_slots(self, text: str) -> Dict[str, Any]:
        """
        Extract Mockingbird-specific slots
        
        Looks for voice preferences, duration, etc.
        """
        slots = {}
        
        # Check for voice characteristics
        voice_gender = self._extract_voice_gender(text)
        if voice_gender:
            slots["voice_gender"] = voice_gender
        
        voice_style = self._extract_voice_style(text)
        if voice_style:
            slots["voice_style"] = voice_style
        
        # Check for confirmation/cancellation
        if self.patterns["yes_no"].search(text):
            response = self.patterns["yes_no"].search(text).group(1).lower()
            slots["confirmation"] = response in ["yes", "yeah", "sure", "okay", "ok"]
        
        return slots
    
    def get_missing_slots(
        self, 
        intent: Intent, 
        filled_slots: Dict[str, Any]
    ) -> List[str]:
        """
        Get list of required slots that are not yet filled
        
        Args:
            intent: Current intent
            filled_slots: Already filled slots
            
        Returns:
            List of missing required slot names
        """
        intent_config = self.intent_slots.get(intent.name, {})
        required_slots = intent_config.get("required", [])
        
        missing = [
            slot for slot in required_slots
            if slot not in filled_slots
        ]
        
        return missing
    
    def validate_slot(self, slot_name: str, slot_value: Any) -> bool:
        """
        Validate a slot value
        
        Ensures the extracted value is valid for the slot type
        """
        # Basic validation - can be extended
        if slot_value is None:
            return False
        
        # Slot-specific validation
        if slot_name == "voice_gender":
            return slot_value in ["male", "female", "neutral"]
        elif slot_name == "voice_style":
            return slot_value in ["professional", "casual", "friendly", "energetic", "calm"]
        
        # Default: non-empty value is valid
        return True
    
    def format_slot_value(self, slot_name: str, slot_value: Any) -> str:
        """
        Format a slot value for display
        
        Makes slot values human-readable
        """
        if isinstance(slot_value, dict):
            # Duration formatting
            if "value" in slot_value and "unit" in slot_value:
                return f"{slot_value['value']} {slot_value['unit']}s"
        
        if isinstance(slot_value, bool):
            return "yes" if slot_value else "no"
        
        return str(slot_value)
    
    def get_slot_question(self, slot_name: str) -> str:
        """
        Generate a question to ask the user for a missing slot
        
        Used during slot-filling dialogue
        """
        questions = {
            "voice_gender": "Would you like a male, female, or neutral voice?",
            "voice_style": "What style would you prefer? Professional, casual, friendly, energetic, or calm?",
            "duration": "How long should this take?",
            "confirmation": "Does that sound good to you?"
        }
        
        return questions.get(
            slot_name,
            f"Could you provide more information about {slot_name.replace('_', ' ')}?"
        )