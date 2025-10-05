"""
Authentication for June Orchestrator
Supports both shared auth module and fallback
"""
import os
import logging
from typing import Dict, Any
from fastapi import HTTPException, Header

from app.config import get_config

logger = logging.getLogger(__name__)

class SharedAuth:
    def __init__(self):
        # Load service tokens from environment variable
        tokens_env = os.getenv("VALID_SERVICE_TOKENS", "")
        if tokens_env:
            # Support comma-separated list of tokens
            self.valid_service_tokens = [token.strip() for token in tokens_env.split(",")]
        else:
            self.valid_service_tokens = []
        
        logger.info(f"✅ SharedAuth initialized with {len(self.valid_service_tokens)} service tokens")
    
    def validate_service_token(self, token: str) -> bool:
        return token in self.valid_service_tokens

# Initialize shared auth
try:
    shared_auth = SharedAuth()
    logger.info("✅ Shared auth initialized successfully")
except Exception as e:
    logger.warning(f"⚠️ Shared auth initialization failed: {e}")
    shared_auth = None

def validate_service_token(token: str) -> bool:
    if shared_auth:
        return shared_auth.validate_service_token(token)
    
    # Fallback validation - should not be needed now
    logger.warning("⚠️ Using fallback token validation")
    return False

async def verify_service_token(authorization: str = Header(None)) -> Dict[str, Any]:
    """
    Verify service-to-service token (for STT calling orchestrator)
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    token = authorization.replace("Bearer ", "").strip()
    
    # Use the new service token validation
    if validate_service_token(token):
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
    # Try to import shared auth for user tokens
    try:
        from shared.auth import get_auth_service, AuthError
        SHARED_AUTH_AVAILABLE = True
    except ImportError:
        SHARED_AUTH_AVAILABLE = False
        logger.warning("⚠️ Shared auth not available for user tokens - returning anonymous user")
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
