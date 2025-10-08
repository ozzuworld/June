import logging
from typing import Dict, Optional
from fastapi import HTTPException

# Use the shared auth module properly
try:
    from shared.auth import get_auth_service, AuthError
    SHARED_AUTH_AVAILABLE = True
except ImportError:
    SHARED_AUTH_AVAILABLE = False

logger = logging.getLogger(__name__)

async def verify_websocket_token(token: str) -> Optional[Dict]:
    """Verify WebSocket token using shared auth service"""
    if not token:
        return None
    
    if not SHARED_AUTH_AVAILABLE:
        logger.warning("Shared auth not available - allowing anonymous access")
        return None
        
    try:
        # Clean token format
        if token.startswith("Bearer "):
            token = token[7:]
            
        auth_service = get_auth_service()
        user_data = await auth_service.verify_bearer(token)
        logger.info(f"Token verified for user: {user_data.get('sub', 'unknown')}")
        return user_data
        
    except AuthError as e:
        logger.warning(f"Token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}")
        return None

async def get_user_from_token(token: str) -> Dict:
    """Get user data or return anonymous user"""
    user = await verify_websocket_token(token)
    return user or {"sub": "anonymous", "username": "anonymous"}

# HTTP endpoint auth dependency  
async def require_auth(authorization: str = None) -> Dict:
    """FastAPI dependency for HTTP endpoints requiring auth"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")
        
    user = await verify_websocket_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    return user

def get_keycloak_user(token: str) -> Optional[Dict]:
    """Legacy function for compatibility - delegates to shared auth"""
    import asyncio
    try:
        return asyncio.run(verify_websocket_token(token))
    except:
        return None

def verify_keycloak_token(token: str) -> bool:
    """Legacy function for compatibility"""
    user = get_keycloak_user(token)
    return user is not None

def get_shared_auth_user(user_id: str) -> Optional[Dict]:
    """Get user by ID - simplified for WebSocket architecture"""
    return {"username": user_id, "sub": user_id}

def get_anonymous_user() -> Dict:
    """Return anonymous user data"""
    return {"sub": "anonymous", "username": "anonymous"}