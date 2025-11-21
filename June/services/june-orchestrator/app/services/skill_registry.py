"""
Skill Registry - Centralized skill management

Phase 2: Provides a registry for all available skills with metadata
"""
import logging
from typing import Dict, Callable, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SkillCategory(Enum):
    """Categories for organizing skills"""
    VOICE = "voice"
    INFORMATION = "information"
    CONTROL = "control"
    ENTERTAINMENT = "entertainment"
    UTILITY = "utility"


@dataclass
class SkillDefinition:
    """
    Definition of a skill with all metadata.

    Attributes:
        name: Unique skill identifier
        category: Skill category
        description: Human-readable description
        intents: List of intents that trigger this skill
        handler: Async function to execute the skill
        requires_confirmation: Whether skill needs user confirmation
        confirmation_message: Message to show when requesting confirmation
        requires_slots: List of required slot names
        optional_slots: List of optional slot names
    """
    name: str
    category: SkillCategory
    description: str
    intents: List[str]
    handler: Callable
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    requires_slots: List[str] = None
    optional_slots: List[str] = None

    def __post_init__(self):
        """Initialize default values"""
        if self.requires_slots is None:
            self.requires_slots = []
        if self.optional_slots is None:
            self.optional_slots = []


class SkillRegistry:
    """
    Central registry for all skills.

    Manages skill registration, lookup, and metadata.
    """

    def __init__(self):
        """Initialize empty registry"""
        self.skills: Dict[str, SkillDefinition] = {}
        self._intent_to_skill: Dict[str, str] = {}  # intent -> skill_name mapping
        logger.info("SkillRegistry initialized")

    def register(self, skill: SkillDefinition):
        """
        Register a skill in the registry.

        Args:
            skill: SkillDefinition to register

        Raises:
            ValueError: If skill name already registered
        """
        if skill.name in self.skills:
            logger.warning(f"Skill '{skill.name}' already registered, overwriting")

        self.skills[skill.name] = skill

        # Build intent mappings
        for intent in skill.intents:
            if intent in self._intent_to_skill:
                logger.warning(
                    f"Intent '{intent}' already mapped to skill '{self._intent_to_skill[intent]}', "
                    f"overwriting with '{skill.name}'"
                )
            self._intent_to_skill[intent] = skill.name

        logger.info(
            f"✅ Registered skill: {skill.name} "
            f"(category: {skill.category.value}, intents: {skill.intents})"
        )

    def unregister(self, skill_name: str):
        """
        Remove a skill from the registry.

        Args:
            skill_name: Name of skill to remove
        """
        if skill_name not in self.skills:
            logger.warning(f"Skill '{skill_name}' not found in registry")
            return

        skill = self.skills[skill_name]

        # Remove intent mappings
        for intent in skill.intents:
            if self._intent_to_skill.get(intent) == skill_name:
                del self._intent_to_skill[intent]

        del self.skills[skill_name]
        logger.info(f"🗑️ Unregistered skill: {skill_name}")

    def get_skill(self, skill_name: str) -> Optional[SkillDefinition]:
        """
        Get skill by name.

        Args:
            skill_name: Name of skill to retrieve

        Returns:
            SkillDefinition or None if not found
        """
        return self.skills.get(skill_name)

    def get_skill_for_intent(self, intent: str) -> Optional[SkillDefinition]:
        """
        Get skill that handles given intent.

        Args:
            intent: Intent name

        Returns:
            SkillDefinition or None if no skill handles this intent
        """
        skill_name = self._intent_to_skill.get(intent)
        if skill_name:
            return self.skills.get(skill_name)
        return None

    def list_skills(
        self,
        category: Optional[SkillCategory] = None,
        requires_confirmation: Optional[bool] = None
    ) -> List[SkillDefinition]:
        """
        List all skills, optionally filtered.

        Args:
            category: Filter by category
            requires_confirmation: Filter by confirmation requirement

        Returns:
            List of SkillDefinitions matching filters
        """
        skills = list(self.skills.values())

        if category is not None:
            skills = [s for s in skills if s.category == category]

        if requires_confirmation is not None:
            skills = [s for s in skills if s.requires_confirmation == requires_confirmation]

        return skills

    def list_intents(self) -> List[str]:
        """
        Get list of all registered intents.

        Returns:
            List of intent names
        """
        return list(self._intent_to_skill.keys())

    def get_stats(self) -> Dict:
        """
        Get registry statistics.

        Returns:
            Dictionary with stats
        """
        category_counts = {}
        for skill in self.skills.values():
            cat = skill.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "total_skills": len(self.skills),
            "total_intents": len(self._intent_to_skill),
            "skills_by_category": category_counts,
            "skills_requiring_confirmation": len([
                s for s in self.skills.values() if s.requires_confirmation
            ])
        }

    def __repr__(self) -> str:
        """String representation"""
        stats = self.get_stats()
        return (
            f"SkillRegistry(skills={stats['total_skills']}, "
            f"intents={stats['total_intents']})"
        )


# ===== CONVENIENCE FUNCTIONS =====

def create_skill_registry_with_defaults() -> SkillRegistry:
    """
    Create a skill registry with default skills pre-registered.

    This is a factory function that creates a registry and registers
    the standard June skills.

    Returns:
        SkillRegistry with default skills registered
    """
    registry = SkillRegistry()

    # Note: Skills will be registered by SkillOrchestrator
    # This function is here for future extensibility

    return registry
