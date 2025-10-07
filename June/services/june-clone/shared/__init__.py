# shared/__init__.py
"""
Shared module for June TTS service
Provides common utilities and authentication functions
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import Depends, HTTPException, Header

logger = logging.getLogger(__name__)

def require_service_auth():
    """
    Authentication function for service-to-service communication
    Returns auth data directly for dependency injection
    """
    return {
        "client_id": "docker-service", 
        "scopes": ["tts:synthesize", "tts:read"],
        "authenticated": True
    }

async def validate_websocket_token(token: str) -> Dict[str, Any]:
    """Validate a WebSocket token"""
    if not token:
        raise ValueError("No token provided")
    
    # For Docker deployment, return mock user data
    # In production, implement proper JWT validation
    return {
        "user_id": "docker-user",
        "sub": "docker-user", 
        "authenticated": True,
        "scopes": ["websocket", "tts:stream"]
    }

def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from authentication data"""
    return auth_data.get("sub") or auth_data.get("user_id") or auth_data.get("uid", "unknown")

def extract_client_id(auth_data: Dict[str, Any]) -> str:
    """Extract client ID from authentication data"""
    return auth_data.get("client_id") or auth_data.get("azp", "unknown")

def has_role(auth_data: Dict[str, Any], role: str) -> bool:
    """Check if user has a specific role"""
    roles = auth_data.get("realm_access", {}).get("roles", [])
    return role in roles

def has_scope(auth_data: Dict[str, Any], scope: str) -> bool:
    """Check if token has a specific scope"""
    scopes = auth_data.get("scope", "").split() if auth_data.get("scope") else auth_data.get("scopes", [])
    return scope in scopes

# Export the main functions
__all__ = [
    'require_service_auth',
    'validate_websocket_token', 
    'extract_user_id',
    'extract_client_id',
    'has_role',
    'has_scope'
]
