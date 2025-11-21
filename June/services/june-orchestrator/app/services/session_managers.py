"""
Session Managers - Manage session-scoped SkillOrchestrator instances

Note: ConversationManager is a singleton that handles multiple sessions internally.
Use get_conversation_manager() from app.core.dependencies instead.
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Global registry for session-scoped SkillOrchestrator instances
_skill_orchestrators: Dict[str, "SkillOrchestrator"] = {}


def get_skill_orchestrator(session_id: str) -> "SkillOrchestrator":
    """
    Get or create SkillOrchestrator for session.

    Args:
        session_id: Unique session identifier

    Returns:
        SkillOrchestrator instance for this session
    """
    if session_id not in _skill_orchestrators:
        logger.info(f"Creating new SkillOrchestrator for session: {session_id}")

        # Import here to avoid circular dependency
        from app.services.skill_orchestrator import SkillOrchestrator

        _skill_orchestrators[session_id] = SkillOrchestrator(session_id)

    return _skill_orchestrators[session_id]


def clear_session(session_id: str):
    """
    Clear session data (call on session end).

    Args:
        session_id: Session to clear
    """
    logger.info(f"Clearing SkillOrchestrator for session: {session_id}")

    if session_id in _skill_orchestrators:
        del _skill_orchestrators[session_id]


def get_active_sessions() -> list:
    """
    Get list of active session IDs with SkillOrchestrators.

    Returns:
        List of active session IDs
    """
    return list(_skill_orchestrators.keys())


def clear_all_sessions():
    """
    Clear all session data. Use with caution!
    """
    logger.warning("Clearing all SkillOrchestrator session data!")
    _skill_orchestrators.clear()
