# June/services/shared/auth.py
"""
Unified authentication system for all June services
Supports both user tokens (Firebase/Keycloak ID tokens) and service-to-service tokens
"""

import os
import time
import logging
import httpx
import jwt
from typing import Optional, Dict, Any, Union
from functools import lru_cache
from dataclasses import dataclass
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)
security = HTTPBearer()

# Configuration
@dataclass
class AuthConfig:
    # Keycloak/Identity Provider settings
    keycloak_url: str
    realm: str = "june"
    
    # JWT settings  
    jwt_signing_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    
    # Firebase settings (fallback)
    firebase_project_id: Optional[str] = None
    
    # Cache settings
    jwks_cache_ttl: int = 3600  # 1 hour
    
    @classmethod
    def from_env(cls) -> "AuthConfig":
        return cls(
            keycloak_url=os.getenv("KEYCLOAK_URL", "http://localhost:8080"),
            realm=os.getenv("KEYCLOAK_REALM", "june"),
            jwt_signing_key=os.getenv("JWT_SIGNING_KEY"),
            firebase_project_id=os.getenv("FIREBASE_PROJECT_ID")
        )

# Global config
_auth_config: Optional[AuthConfig] = None

def get_auth_config() -> AuthConfig:
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig.from_env()
    return _auth_config

class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class JWKSCache:
    """Cache for JWT public keys"""
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, float] = {}
        
    async def get_jwks(self, jwks_url: str, ttl: int = 3600) -> Dict[str, Any]:
        now = time.time()
        
        if (jwks_url in self._cache and 
            jwks_url in self._cache_time and 
            now - self._cache_time[jwks_url] < ttl):
            return self._cache[jwks_url]
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                
                jwks = response.json()
                self._cache[jwks_url] = jwks
                self._cache_time[jwks_url] = now
                
                return jwks
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
            raise AuthError(f"Failed to fetch public keys: {e}", 503)

# Global JWKS cache
_jwks_cache = JWKSCache()

class AuthService:
    """Unified authentication service"""
    
    def __init__(self, config: AuthConfig):
        self.config = config
        
    async def validate_user_token(self, token: str) -> Dict[str, Any]:
        """Validate user ID token (Firebase or Keycloak)"""
        
        # Try Keycloak first if configured
        if self.config.keycloak_url:
            try:
                return await self._validate_keycloak_token(token)
            except AuthError:
                pass  # Fall back to other methods
                
        # Try Firebase if configured
        if self.config.firebase_project_id:
            try:
                return await self._validate_firebase_token(token)
            except AuthError:
                pass
                
        # Try symmetric JWT if key is configured
        if self.config.jwt_signing_key:
            try:
                return self._validate_symmetric_jwt(token)
            except AuthError:
                pass
                
        raise AuthError("Invalid or unsupported token format")
        
    async def validate_service_token(self, token: str) -> Dict[str, Any]:
        """Validate service-to-service token"""
        
        if self.config.keycloak_url:
            return await self._validate_keycloak_service_token(token)
        elif self.config.jwt_signing_key:
            return self._validate_symmetric_jwt(token, audience="service")
        else:
            raise AuthError("Service authentication not configured")
            
    async def _validate_keycloak_token(self, token: str) -> Dict[str, Any]:
        """Validate Keycloak/OIDC token using JWKS"""
        try:
            # Get unverified header to find key ID
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            
            if not kid:
                raise AuthError("Token missing key ID")
                
            # Get JWKS
            jwks_url = f"{self.config.keycloak_url}/realms/{self.config.realm}/protocol/openid-connect/certs"
            jwks = await _jwks_cache.get_jwks(jwks_url, self.config.jwks_cache_ttl)
            
            # Find matching key
            key = None
            for jwk in jwks.get("keys", []):
                if jwk.get("kid") == kid:
                    key = jwk
                    break
                    
            if not key:
                raise AuthError("Token key not found in JWKS")
                
            # Convert JWK to PEM
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            
            # Validate token
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=["account"],  # Keycloak default
                issuer=f"{self.config.keycloak_url}/realms/{self.config.realm}",
                options={"verify_exp": True, "verify_iat": True}
            )
            
            return {
                "user_id": payload.get("sub"),
                "email": payload.get("email"),
                "username": payload.get("preferred_username"),
                "roles": payload.get("realm_access", {}).get("roles", []),
                "client_id": payload.get("azp"),
                "token_type": "user",
                "raw_payload": payload
            }
            
        except jwt.ExpiredSignatureError:
            raise AuthError("Token expired")
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid token: {e}")
        except Exception as e:
            logger.error(f"Keycloak token validation error: {e}")
            raise AuthError("Token validation failed")
            
    async def _validate_keycloak_service_token(self, token: str) -> Dict[str, Any]:
        """Validate service account token from Keycloak"""
        user_data = await self._validate_keycloak_token(token)
        
        # Ensure it's a service account token
        if not user_data.get("client_id"):
            raise AuthError("Not a service account token")
            
        return {
            "client_id": user_data["client_id"],
            "service_name": user_data.get("username", user_data["client_id"]),
            "scopes": user_data.get("scope", "").split(),
            "token_type": "service",
            "raw_payload": user_data["raw_payload"]
        }
        
    async def _validate_firebase_token(self, token: str) -> Dict[str, Any]:
        """Validate Firebase ID token"""
        try:
            # Import here to make Firebase optional
            import firebase_admin
            from firebase_admin import auth as fb_auth
            
            # Initialize if needed
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
                
            claims = fb_auth.verify_id_token(token)
            
            return {
                "user_id": claims.get("uid"),
                "email": claims.get("email"),
                "username": claims.get("name"),
                "token_type": "user",
                "raw_payload": claims
            }
            
        except ImportError:
            raise AuthError("Firebase authentication not available")
        except Exception as e:
            raise AuthError(f"Firebase token validation failed: {e}")
            
    def _validate_symmetric_jwt(self, token: str, audience: str = "user") -> Dict[str, Any]:
        """Validate JWT with symmetric key"""
        try:
            if not self.config.jwt_signing_key:
                raise AuthError("JWT signing key not configured")
                
            payload = jwt.decode(
                token,
                self.config.jwt_signing_key,
                algorithms=[self.config.jwt_algorithm],
                options={"verify_exp": True, "verify_iat": True}
            )
            
            return {
                "user_id": payload.get("sub"),
                "client_id": payload.get("client_id"),
                "scopes": payload.get("scope", "").split(),
                "session_id": payload.get("sid"),
                "token_type": audience,
                "raw_payload": payload
            }
            
        except jwt.ExpiredSignatureError:
            raise AuthError("Token expired")
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid JWT: {e}")

# Global auth service instance
_auth_service: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(get_auth_config())
    return _auth_service

# FastAPI Dependencies
async def require_user_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """FastAPI dependency for user authentication"""
    try:
        auth_service = get_auth_service()
        user_data = await auth_service.validate_user_token(credentials.credentials)
        
        if user_data["token_type"] != "user":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User token required"
            )
            
        return user_data
        
    except AuthError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message
        )
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

async def require_service_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security)  
) -> Dict[str, Any]:
    """FastAPI dependency for service-to-service authentication"""
    try:
        auth_service = get_auth_service()
        service_data = await auth_service.validate_service_token(credentials.credentials)
        
        if service_data["token_type"] != "service":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Service token required"
            )
            
        return service_data
        
    except AuthError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message
        )
    except Exception as e:
        logger.error(f"Service authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

async def optional_user_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[Dict[str, Any]]:
    """Optional user authentication - returns None if no token provided"""
    if not credentials:
        return None
        
    try:
        auth_service = get_auth_service()
        return await auth_service.validate_user_token(credentials.credentials)
    except AuthError:
        return None
    except Exception as e:
        logger.error(f"Optional auth error: {e}")
        return None

# WebSocket authentication helper  
async def validate_websocket_token(token: Optional[str]) -> Dict[str, Any]:
    """Validate token for WebSocket connections"""
    if not token:
        raise AuthError("Missing authentication token")
        
    auth_service = get_auth_service()
    return await auth_service.validate_user_token(token)

# Utility functions
def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from auth data"""
    return auth_data.get("user_id") or auth_data.get("sub", "")

def extract_client_id(auth_data: Dict[str, Any]) -> Optional[str]:
    """Extract client/service ID from auth data"""
    return auth_data.get("client_id")

def has_role(auth_data: Dict[str, Any], role: str) -> bool:
    """Check if user has specific role"""
    roles = auth_data.get("roles", [])
    return role in roles

def has_scope(auth_data: Dict[str, Any], scope: str) -> bool:
    """Check if token has specific scope"""
    scopes = auth_data.get("scopes", [])
    return scope in scopes