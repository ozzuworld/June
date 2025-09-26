# June/services/shared/__init__.py
"""Shared utilities for June services"""

from .auth import (
    require_user_auth,
    require_service_auth, 
    optional_user_auth,
    validate_websocket_token,
    extract_user_id,
    extract_client_id,
    has_role,
    has_scope,
    AuthConfig,
    AuthError
)

__all__ = [
    "require_user_auth",
    "require_service_auth",
    "optional_user_auth", 
    "validate_websocket_token",
    "extract_user_id",
    "extract_client_id",
    "has_role",
    "has_scope",
    "AuthConfig",
    "AuthError"
]