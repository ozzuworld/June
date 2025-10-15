"""Dependencies and auth helpers (with logging)"""
import logging

logger = logging.getLogger(__name__)

# TODO: Replace this stub with your real Keycloak verification.
# Keep the logging lines. Do NOT add *args or **kwargs here, to avoid FastAPI
# treating them as required query parameters.
async def get_current_user():
    logger.info("[AUTH] get_current_user called")
    try:
        # Placeholder user to keep the flow working during debugging.
        user = {"sub": "test-user", "email": "test@example.com"}
        logger.info(f"[AUTH] get_current_user success: sub={user.get('sub')} email={user.get('email')}")
        return user
    except Exception as e:
        logger.exception(f"[AUTH] get_current_user failed: {e}")
        raise
