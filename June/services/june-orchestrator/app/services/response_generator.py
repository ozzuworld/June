"""
Response Generator - Natural, context-aware responses

Phase 3: Generates responses that feel natural based on:
- Dialogue state
- Conversation context
- User preferences
- Time of day
"""
import logging
import random
from typing import Dict, List, Optional
from datetime import datetime

from app.services.dialogue_state import DialogueState, ConversationContext

logger = logging.getLogger(__name__)


class ResponseGenerator:
    """
    Generates natural language responses based on conversation context.

    Makes responses feel more human-like by:
    - Adding state-aware prefixes
    - Personalizing with user info
    - Adding continuity markers
    - Time-appropriate greetings
    """

    def __init__(self):
        """Initialize response generator"""
        self.response_templates = self._load_templates()
        logger.info("ResponseGenerator initialized")

    def generate(
        self,
        base_response: str,
        dialogue_state: DialogueState,
        context: ConversationContext,
        intent: str = "general"
    ) -> str:
        """
        Enhance base response with state-aware phrasing.

        Args:
            base_response: Base response text
            dialogue_state: Current dialogue state
            context: Conversation context
            intent: Intent being responded to

        Returns:
            Enhanced natural language response
        """
        # Start with base response
        response = base_response

        # Add personalization
        response = self._personalize(response, context)

        # Add state-aware prefix (for certain states)
        prefix = self._get_state_prefix(dialogue_state, context)
        if prefix:
            response = f"{prefix}{response}"

        # Add continuity markers if in multi-turn conversation
        if context.turn_count > 1 and dialogue_state == DialogueState.GENERAL_CONVERSATION:
            response = self._add_continuity_markers(response, context)

        return response

    def generate_greeting(self, context: ConversationContext) -> str:
        """
        Generate time-appropriate greeting.

        Args:
            context: Conversation context

        Returns:
            Natural greeting
        """
        time_of_day = self._get_time_of_day()
        user_name = context.user_profile.get("name", "")

        greetings = {
            "morning": [
                f"Good morning{' ' + user_name if user_name else ''}! How can I help you today?",
                f"Morning{' ' + user_name if user_name else ''}! What can I do for you?",
                f"Hello{' ' + user_name if user_name else ''}! Good morning! What's on your mind?"
            ],
            "afternoon": [
                f"Good afternoon{' ' + user_name if user_name else ''}! How can I assist you?",
                f"Hello{' ' + user_name if user_name else ''}! What can I help you with this afternoon?",
                f"Hi{' ' + user_name if user_name else ''}! How's your afternoon going? What do you need?"
            ],
            "evening": [
                f"Good evening{' ' + user_name if user_name else ''}! What can I do for you?",
                f"Evening{' ' + user_name if user_name else ''}! How can I help?",
                f"Hello{' ' + user_name if user_name else ''}! What brings you here this evening?"
            ]
        }

        # Pick a random greeting for variety
        options = greetings.get(time_of_day, greetings["morning"])
        return random.choice(options)

    def generate_error_recovery(self, context: ConversationContext) -> str:
        """
        Generate natural error recovery message.

        Args:
            context: Conversation context

        Returns:
            Error recovery message
        """
        options = [
            "Sorry about that. Could you try rephrasing?",
            "I'm having trouble with that. Can you say it differently?",
            "Hmm, I didn't quite catch that. Could you rephrase?",
            "My apologies, I'm not sure I understood. Can you try again?"
        ]
        return random.choice(options)

    def generate_clarification(
        self,
        unclear_part: str,
        context: ConversationContext
    ) -> str:
        """
        Generate clarification request.

        Args:
            unclear_part: What part needs clarification
            context: Conversation context

        Returns:
            Clarification request
        """
        options = [
            f"I'm not sure I understood {unclear_part}. Could you clarify?",
            f"Can you tell me more about {unclear_part}?",
            f"Just to make sure I understand, what did you mean by {unclear_part}?",
            f"Could you explain {unclear_part} a bit more?"
        ]
        return random.choice(options)

    # ==================== PRIVATE HELPER METHODS ====================

    def _get_state_prefix(
        self,
        state: DialogueState,
        context: ConversationContext
    ) -> str:
        """
        Get natural prefix based on dialogue state.

        Args:
            state: Current dialogue state
            context: Conversation context

        Returns:
            Prefix string or empty string
        """
        if state == DialogueState.GREETING:
            # Greeting already generated with time awareness
            return ""

        elif state == DialogueState.CONFIRMATION:
            return "Just to confirm - "

        elif state == DialogueState.ERROR_RECOVERY:
            return "Sorry about that. "

        elif state == DialogueState.SLOT_FILLING:
            return "Got it. "

        elif state == DialogueState.CLARIFICATION:
            return "Let me make sure I understand. "

        return ""

    def _personalize(
        self,
        response: str,
        context: ConversationContext
    ) -> str:
        """
        Add personalization based on user profile.

        Args:
            response: Response text
            context: Conversation context

        Returns:
            Personalized response
        """
        # Replace {name} placeholder if present
        user_name = context.user_profile.get("name", "")
        if user_name and "{name}" in response:
            response = response.replace("{name}", user_name)

        # Could add more personalization here based on preferences
        # e.g., formality level, verbosity, etc.

        return response

    def _add_continuity_markers(
        self,
        response: str,
        context: ConversationContext
    ) -> str:
        """
        Add conversational continuity markers.

        Args:
            response: Response text
            context: Conversation context

        Returns:
            Response with continuity markers
        """
        # Don't add markers if response already starts with one
        starts_with_marker = any(
            response.lower().startswith(marker)
            for marker in ["also", "and", "by the way", "additionally", "furthermore"]
        )

        if starts_with_marker:
            return response

        # Add transition markers occasionally for natural flow
        # Only if we have recent context
        if context.turn_count > 2 and random.random() < 0.2:  # 20% chance
            transitions = ["Also, ", "By the way, ", "Additionally, "]
            return random.choice(transitions) + response

        return response

    def _get_time_of_day(self) -> str:
        """
        Get current time of day category.

        Returns:
            "morning", "afternoon", or "evening"
        """
        hour = datetime.now().hour

        if hour < 12:
            return "morning"
        elif hour < 17:
            return "afternoon"
        else:
            return "evening"

    def _load_templates(self) -> Dict[str, List[str]]:
        """
        Load response templates for different situations.

        Returns:
            Dictionary of template lists
        """
        return {
            "error": [
                "I'm having trouble with that. Could you try rephrasing?",
                "Sorry, I didn't quite catch that. Can you say that again?",
                "I'm not sure I understood. Could you explain differently?"
            ],
            "success": [
                "Done!",
                "All set!",
                "Got it!",
                "No problem!",
                "There you go!"
            ],
            "thinking": [
                "Let me think about that...",
                "One moment...",
                "Give me a second...",
                "Let me check on that..."
            ],
            "acknowledgment": [
                "I understand.",
                "Got it.",
                "Okay.",
                "I see.",
                "Understood."
            ]
        }

    def get_random_template(self, category: str) -> str:
        """
        Get a random template from a category.

        Args:
            category: Template category

        Returns:
            Random template string
        """
        templates = self.response_templates.get(category, [""])
        return random.choice(templates) if templates else ""


# ===== CONVENIENCE FUNCTIONS =====

def enhance_response(
    base_response: str,
    context: ConversationContext,
    dialogue_state: Optional[DialogueState] = None
) -> str:
    """
    Quick function to enhance a response without creating ResponseGenerator instance.

    Args:
        base_response: Base response text
        context: Conversation context
        dialogue_state: Optional dialogue state (defaults to context.current_state)

    Returns:
        Enhanced response
    """
    generator = ResponseGenerator()
    state = dialogue_state if dialogue_state else context.current_state
    return generator.generate(base_response, state, context)
