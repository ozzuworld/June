# June/services/june-stt/shared/auth.py
import os
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, Header

logger = logging.getLogger(__name__)

class AuthConfig:
    def __init__(self):
        self.keycloak_url = os.getenv("KEYCLOAK_URL")
        self.realm = os.getenv("KEYCLOAK_REALM", "allsafe")
        self.fallback_mode = not self.keycloak_url

async def require_user_auth(authorization: str = Header(None)) -> Dict[str, Any]:
    """
    Require user authentication for STT endpoints
    Compatible with orchestrator's service-to-service calls
    """
    config = AuthConfig()
    
    if config.fallback_mode:
        # Development/Docker mode - allow requests but log
        logger.info("STT running in fallback auth mode")
        return {
            "sub": "stt-user",
            "client_id": "june-stt",
            "authenticated": True,
            "scopes": ["stt:transcribe", "stt:read"]
        }
    
    # In production, implement proper JWT validation
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    # For now, mock validation - replace with proper JWT validation
    token = authorization[7:]  # Remove "Bearer "
    
    return {
        "sub": "validated-user",
        "client_id": "june-orchestrator", 
        "authenticated": True,
        "scopes": ["stt:transcribe", "stt:read"]
    }

async def require_service_auth() -> Dict[str, Any]:
    """Service-to-service authentication for orchestrator calls"""
    return {
        "client_id": "june-orchestrator",
        "authenticated": True,
        "scopes": ["stt:transcribe", "stt:read", "service:access"]
    }

def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from auth data"""
    return auth_data.get("sub") or auth_data.get("user_id", "unknown")

def extract_client_id(auth_data: Dict[str, Any]) -> str:
    """Extract client ID from auth data"""
    return auth_data.get("client_id", "unknown")