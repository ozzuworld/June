"""Dependencies and auth helpers (with logging)"""
import logging

logger = logging.getLogger(__name__)

# NOTE: Replace the body of this function with your real auth logic.
# The logging lines are safe to keep.
async def get_current_user(*args, **kwargs):
    logger.info("[AUTH] get_current_user called")
    try:
        # TODO: Insert real bearer token verification here and return a user dict.
        # Example placeholder to keep service running while debugging:
        user = kwargs.get("user") or {"sub": "test-user", "email": "test@example.com"}
        logger.info(f"[AUTH] get_current_user success: sub={user.get('sub')} email={user.get('email')}")
        return user
    except Exception as e:
        logger.exception(f"[AUTH] get_current_user failed: {e}")
        raise
