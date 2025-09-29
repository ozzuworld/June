# June/services/june-tts/shared/__init__.py
"""
Shared module for June TTS service with proper service authentication
"""

import os
import asyncio
from typing import Dict, Any
from fastapi import HTTPException, Header
import logging

logger = logging.getLogger(__name__)

# Try to import full auth module
try:
    from shared.auth import (
        require_user_auth as _require_user_auth,
        require_service_auth as _require_service_auth,
        extract_user_id as _extract_user_id,
        extract_client_id as _extract_client_id
    )
    FULL_AUTH_AVAILABLE = True
    logger.info("✅ Full authentication module loaded")
except ImportError:
    FULL_AUTH_AVAILABLE = False
    logger.warning("⚠️ Full authentication not available - using fallback")


async def require_service_auth(authorization: str = Header(None)):
    """
    Require service authentication
    Falls back to mock if full auth not available
    """
    if FULL_AUTH_AVAILABLE:
        return await _require_service_auth(authorization)
    else:
        # Fallback for development
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization required")
        return {
            "client_id": "fallback-service",
            "authenticated": True,
            "scopes": ["tts:synthesize", "tts:read"]
        }


async def require_user_auth(authorization: str = Header(None)):
    """
    Require user authentication
    Falls back to mock if full auth not available
    """
    if FULL_AUTH_AVAILABLE:
        return await _require_user_auth(authorization)
    else:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization required")
        return {
            "sub": "fallback-user",
            "authenticated": True
        }


def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from auth data"""
    if FULL_AUTH_AVAILABLE:
        return _extract_user_id(auth_data)
    return auth_data.get("sub", "unknown")


def extract_client_id(auth_data: Dict[str, Any]) -> str:
    """Extract client ID from auth data"""
    if FULL_AUTH_AVAILABLE:
        return _extract_client_id(auth_data)
    return auth_data.get("client_id", "unknown")


__all__ = [
    'require_service_auth',
    'require_user_auth',
    'extract_user_id',
    'extract_client_id'
]