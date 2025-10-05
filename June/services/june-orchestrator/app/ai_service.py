"""
Authentication for June Orchestrator
Supports both shared auth module and fallback
"""
import logging
from typing import Dict, Any
from fastapi import HTTPException, Header

from app.config import get_config

logger = logging.getLogger(__name__)

# Try to import shared auth
try:
    from shared.auth import get_auth_service, AuthError
    SHARED_AUTH_AVAILABLE = True
    logger.info("✅ Shared auth module loaded")
except ImportError:
    SHARED_AUTH_AVAILABLE = False
    logger.warning("⚠️ Shared auth not available - using fallback")


async def verify_service_token(authorization: str = Header(None)) -> Dict[str, Any]:
    """
    Verify service-to-service token (for STT calling orchestrator)
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    token = authorization.replace("Bearer ", "").strip()
    config = get_config()
    
    # Validate service token
    if token == config["stt_service_token"]:
        logger.debug("✅ Service authenticated: june-stt")
        return {
            "service": "june-stt",
            "authenticated": True,
            "type": "service_to_service"
        }
    
    raise HTTPException(status_code=401, detail="Invalid service token")


async def verify_user_token(authorization: str = Header(None)) -> Dict[str, Any]:
    """
    Verify user authentication token from frontend
    """
    if not SHARED_AUTH_AVAILABLE:
        logger.warning("⚠️ Auth disabled - returning anonymous user")
        return {"sub": "anonymous", "authenticated": False}
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    token = authorization.replace("Bearer ", "").strip()
    
    try:
        auth_service = get_auth_service()
        token_data = await auth_service.verify_bearer(token)
        
        user_id = token_data.get('sub', 'unknown')
        logger.debug(f"✅ User authenticated: {user_id}")
        return token_data
        
    except Exception as e:
        logger.error(f"❌ User authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from auth data"""
    return auth_data.get("sub") or auth_data.get("user_id", "anonymous")