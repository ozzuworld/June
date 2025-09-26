# June/services/shared/auth.py - FIXED for mobile app tokens
import os
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import httpx
import jwt
from jwt import PyJWKClient, InvalidTokenError, InvalidSignatureError, InvalidAudienceError
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer

class AuthError(Exception):
    pass

@dataclass
class AuthConfig:
    keycloak_url: str
    realm: str
    jwks_cache_ttl: int = 300
    accepted_audiences: List[str] = None  # FIXED: Accept multiple audiences
    jwt_signing_key: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AuthConfig":
        url = os.getenv("KEYCLOAK_URL") or os.getenv("KC_BASE_URL")
        realm = os.getenv("KEYCLOAK_REALM") or os.getenv("KC_REALM")
        if not url:
            raise AuthError("KEYCLOAK_URL (or KC_BASE_URL) is not set")
        if not realm:
            raise AuthError("KEYCLOAK_REALM (or KC_REALM) is not set")

        # FIXED: Support multiple audiences
        audiences = []
        if os.getenv("OIDC_AUDIENCE"):
            audiences.append(os.getenv("OIDC_AUDIENCE"))
        if os.getenv("OIDC_ACCEPTED_AUDIENCES"):
            audiences.extend(os.getenv("OIDC_ACCEPTED_AUDIENCES").split(","))
        
        # Default audiences if none specified
        if not audiences:
            audiences = ["june-mobile-app", "june-orchestrator", "account"]

        return cls(
            keycloak_url=url.rstrip("/"),
            realm=realm,
            jwks_cache_ttl=int(os.getenv("JWKS_CACHE_TTL", "300")),
            accepted_audiences=audiences,
            jwt_signing_key=os.getenv("JWT_SIGNING_KEY"),
        )

class _JWKSCache:
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, url: str, ttl: int) -> Dict[str, Any]:
        now = time.time()
        async with self._lock:
            entry = self._cache.get(url)
            if entry and (now - entry["ts"] < ttl):
                return entry["data"]

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        async with self._lock:
            self._cache[url] = {"data": data, "ts": now}

        return data

_JWKS = _JWKSCache()

class AuthService:
    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig.from_env()

    async def _fetch_oidc_config(self) -> Dict[str, Any]:
        discovery = f"{self.config.keycloak_url}/realms/{self.config.realm}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(discovery)
            r.raise_for_status()
            return r.json()

    async def verify_bearer(self, token: str) -> Dict[str, Any]:
        if not token:
            raise AuthError("Missing bearer token")

        try:
            oidc = await self._fetch_oidc_config()
            issuer = oidc["issuer"]
            jwks_uri = oidc["jwks_uri"]
        except Exception as e:
            raise AuthError(f"OIDC discovery failed: {e}") from e

        try:
            # Use JWKS to get signing key
            jwk_client = PyJWKClient(jwks_uri)
            signing_key = jwk_client.get_signing_key_from_jwt(token).key

            # FIXED: Validate against any accepted audience
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                issuer=issuer,
                options={"verify_aud": False}  # We'll check audience manually
            )
            
            # FIXED: Manual audience validation for multiple accepted audiences
            token_aud = decoded.get("aud", [])
            if isinstance(token_aud, str):
                token_aud = [token_aud]
            
            if self.config.accepted_audiences:
                aud_match = any(aud in self.config.accepted_audiences for aud in token_aud)
                if not aud_match:
                    raise AuthError(f"Token audience {token_aud} not in accepted audiences {self.config.accepted_audiences}")
            
            return decoded

        except InvalidSignatureError as e:
            raise AuthError(f"Token signature invalid: {e}") from e
        except InvalidTokenError as e:
            raise AuthError(f"Token invalid: {e}") from e
        except Exception as e:
            raise AuthError(f"Token verification error: {e}") from e

# Global auth service instance
_auth_service = None

def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

# Security scheme
security = HTTPBearer()

async def require_user_auth(credentials = Depends(security)) -> Dict[str, Any]:
    """Require valid user authentication"""
    try:
        auth_service = get_auth_service()
        token = credentials.credentials
        user_data = await auth_service.verify_bearer(token)
        return user_data
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

async def require_service_auth(credentials = Depends(security)) -> Dict[str, Any]:
    """Require valid service authentication"""
    try:
        auth_service = get_auth_service()
        token = credentials.credentials
        service_data = await auth_service.verify_bearer(token)
        
        # Additional validation for service tokens
        if "client_id" not in service_data:
            raise AuthError("Service token must have client_id claim")
            
        return service_data
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

async def optional_user_auth(credentials = Depends(security)) -> Optional[Dict[str, Any]]:
    """Optional user authentication"""
    if not credentials:
        return None
    try:
        auth_service = get_auth_service()
        return await auth_service.verify_bearer(credentials.credentials)
    except AuthError:
        return None

def extract_user_id(user_data: Dict[str, Any]) -> str:
    """Extract user ID from token data"""
    return user_data.get("sub") or user_data.get("user_id") or "unknown"

def extract_client_id(token_data: Dict[str, Any]) -> str:
    """Extract client ID from token data"""
    return token_data.get("azp") or token_data.get("client_id") or "unknown"

def has_role(user_data: Dict[str, Any], role: str) -> bool:
    """Check if user has a specific role"""
    realm_access = user_data.get("realm_access", {})
    roles = realm_access.get("roles", [])
    return role in roles

def has_scope(token_data: Dict[str, Any], scope: str) -> bool:
    """Check if token has a specific scope"""
    scopes = token_data.get("scope", "").split()
    return scope in scopes

# WebSocket token validation
async def validate_websocket_token(token: str) -> Dict[str, Any]:
    """Validate token for WebSocket connections"""
    if not token:
        raise AuthError("Missing WebSocket token")
    
    auth_service = get_auth_service()
    return await auth_service.verify_bearer(token)

# Test function for debugging
async def test_keycloak_connection():
    """Test Keycloak connection for debugging"""
    try:
        auth_service = get_auth_service()
        oidc_config = await auth_service._fetch_oidc_config()
        
        return {
            "status": "success",
            "issuer": oidc_config.get("issuer"),
            "jwks_uri": oidc_config.get("jwks_uri"),
            "supported_grant_types": oidc_config.get("grant_types_supported"),
            "accepted_audiences": auth_service.config.accepted_audiences,
        }
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e),
            "config": {
                "keycloak_url": auth_service.config.keycloak_url,
                "realm": auth_service.config.realm,
                "accepted_audiences": auth_service.config.accepted_audiences,
            }
        }