"""Skill-Based AI System

Implements June's expandable skill system including the mockingbird voice cloning skill.
"""
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SkillType(str, Enum):
    """Types of skills June can perform"""
    VOICE_CLONING = "voice_cloning"
    LANGUAGE = "language"
    TEXT_PROCESSING = "text_processing"
    ENTERTAINMENT = "entertainment"
    UTILITY = "utility"


class SkillDefinition(BaseModel):
    """Definition of a skill"""
    name: str
    skill_type: SkillType
    triggers: List[str]  # Phrases that activate the skill
    description: str
    activation_response: str
    help_text: str
    requires_input: bool = True  # Does skill need user input after activation?
    max_context_turns: int = 5  # How many turns to stay in skill mode


class SkillSession(BaseModel):
    """Active skill session state"""
    skill_name: Optional[str] = None
    context: Dict[str, Any] = {}
    turn_count: int = 0
    activated_at: Optional[str] = None
    waiting_for_input: bool = False


class SkillService:
    """Service for managing June's skills"""
    
    def __init__(self):
        self.skills = self._initialize_skills()
        logger.info(f"🤖 Initialized {len(self.skills)} skills: {list(self.skills.keys())}")
    
    def _initialize_skills(self) -> Dict[str, SkillDefinition]:
        """Initialize available skills"""
        return {
            "mockingbird": SkillDefinition(
                name="mockingbird",
                skill_type=SkillType.VOICE_CLONING,
                triggers=[
                    "use your skill mockingbird",
                    "activate mockingbird",
                    "mockingbird mode",
                    "show me voice cloning",
                    "demonstrate voice cloning",
                    "mimic my voice",
                    "copy my voice"
                ],
                description="Voice cloning demonstration - June mimics user voices",
                activation_response="🎭 Mockingbird skill activated! I can demonstrate voice cloning by mimicking voices. Say something, and I'll speak back in your voice as a demonstration.",
                help_text="Say 'June, use your skill mockingbird' to activate voice cloning demonstrations",
                requires_input=True,
                max_context_turns=3
            ),
            
            "translator": SkillDefinition(
                name="translator",
                skill_type=SkillType.LANGUAGE,
                triggers=[
                    "translate this",
                    "use your skill translator",
                    "translate to"
                ],
                description="Multi-language translation with voice synthesis",
                activation_response="🌍 Translation skill activated! Tell me what to translate and to which language.",
                help_text="Say 'June, translate this to Spanish' to activate translation",
                requires_input=True,
                max_context_turns=2
            ),
            
            "storyteller": SkillDefinition(
                name="storyteller",
                skill_type=SkillType.ENTERTAINMENT,
                triggers=[
                    "tell me a story",
                    "use your skill storyteller",
                    "story mode"
                ],
                description="Interactive storytelling with character voices",
                activation_response="📚 Storyteller skill activated! I'll tell you an interactive story. What genre would you like?",
                help_text="Say 'June, tell me a story' to activate storytelling mode",
                requires_input=True,
                max_context_turns=10
            )
        }
    
    def detect_skill_trigger(self, text: str) -> Optional[Tuple[str, SkillDefinition]]:
        """Detect if text contains a skill trigger"""
        text_lower = text.lower().strip()
        
        for skill_name, skill in self.skills.items():
            for trigger in skill.triggers:
                if trigger.lower() in text_lower:
                    logger.info(f"🎯 Detected skill trigger: '{trigger}' -> {skill_name}")
                    return skill_name, skill
        
        return None
    
    def get_skill(self, skill_name: str) -> Optional[SkillDefinition]:
        """Get skill definition by name"""
        return self.skills.get(skill_name)
    
    def list_skills(self) -> Dict[str, SkillDefinition]:
        """Get all available skills"""
        return self.skills
    
    def should_exit_skill(self, text: str, skill_session: SkillSession) -> bool:
        """Check if user wants to exit current skill"""
        exit_phrases = [
            "exit", "quit", "stop", "cancel", "back to normal", 
            "normal mode", "disable skill", "turn off"
        ]
        
        text_lower = text.lower().strip()
        for phrase in exit_phrases:
            if phrase in text_lower:
                return True
        
        # Auto-exit after max turns
        if skill_session.turn_count >= self.skills[skill_session.skill_name].max_context_turns:
            logger.info(f"🔄 Auto-exiting skill {skill_session.skill_name} after {skill_session.turn_count} turns")
            return True
        
        return False
    
    def create_skill_response(
        self, 
        skill_name: str, 
        user_input: str, 
        skill_context: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate skill-specific responses"""
        
        if skill_name == "mockingbird":
            return self._handle_mockingbird_skill(user_input, skill_context)
        elif skill_name == "translator":
            return self._handle_translator_skill(user_input, skill_context)
        elif skill_name == "storyteller":
            return self._handle_storyteller_skill(user_input, skill_context)
        else:
            return "I don't know how to handle that skill yet.", skill_context
    
    def _handle_mockingbird_skill(self, user_input: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Handle mockingbird voice cloning skill"""
        
        if not context.get("reference_captured"):
            # First interaction - capture voice for cloning
            context["reference_captured"] = True
            context["reference_text"] = user_input
            
            responses = [
                f"Perfect! I heard you say: '{user_input}'. Now let me demonstrate by speaking in your voice...",
                f"Got it! You said '{user_input}'. Here's how you sound when I mimic your voice:",
                f"Excellent! I captured: '{user_input}'. Let me show you the voice cloning in action:"
            ]
            
            import random
            response = random.choice(responses)
            
            # Mark that we should use voice cloning for the response
            context["use_voice_cloning"] = True
            context["cloning_demonstration"] = True
            
            return response, context
        
        else:
            # Subsequent interactions - can continue demonstrating or exit
            if "more" in user_input.lower() or "again" in user_input.lower():
                context["use_voice_cloning"] = True
                return f"Sure! Here's another demonstration in your voice: {user_input}", context
            else:
                # Exit skill
                return "Mockingbird demonstration complete! Pretty cool, right? I'm returning to my normal voice now.", {}
    
    def _handle_translator_skill(self, user_input: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Handle translation skill (placeholder for future implementation)"""
        return "Translation skill is not fully implemented yet. Coming soon!", context
    
    def _handle_storyteller_skill(self, user_input: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Handle storyteller skill (placeholder for future implementation)"""
        return "Storyteller skill is not fully implemented yet. Coming soon!", context
    
    def get_skill_help(self) -> str:
        """Get help text for all skills"""
        help_lines = ["Here are my available skills:"]
        
        for skill_name, skill in self.skills.items():
            status = "✅ Ready" if skill_name == "mockingbird" else "🚧 Coming Soon"
            help_lines.append(f"\n🔹 **{skill.name.title()}** ({status})")
            help_lines.append(f"   {skill.description}")
            help_lines.append(f"   {skill.help_text}")
        
        help_lines.append("\nTo exit any skill, just say 'exit' or 'back to normal'.")
        
        return "\n".join(help_lines)


# Global skill service instance
skill_service = SkillService()