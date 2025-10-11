"""
FastAPI Dependencies
Authentication, validation, etc.
"""
import logging
from typing import Dict, Any, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


async def simple_auth(authorization: str = Header(None)) -> Dict[str, str]:
    """
    Simplified authentication for development
    Replace with proper JWT validation in production
    """
    if not authorization:
        # For development - allow unauthenticated
        return {"user_id": "anonymous"}
    
    # Remove 'Bearer ' prefix
    token = authorization.replace("Bearer ", "").replace("Bearer%20", "")
    
    # TODO: Validate JWT token properly
    # For now, extract user_id from token
    return {"user_id": f"user_{token[:8]}"}


async def get_current_user(auth_data: dict = None) -> str:
    """Extract user ID from auth data"""
    if not auth_data:
        return "anonymous"
    return auth_data.get("user_id", "anonymous")