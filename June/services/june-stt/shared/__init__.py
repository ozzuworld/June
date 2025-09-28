# June/services/june-stt/shared/auth.py - External service authentication
import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient, InvalidTokenError, InvalidSignatureError, InvalidAudienceError
from fastapi import HTTPException, Header, Depends
from fastapi.security import HTTPBearer

logger = logging.getLogger(__name__)

security = HTTPBearer()

@dataclass
class AuthConfig:
    keycloak_url: str
    realm: str
    client_id: str
    client_secret: str
    jwks_cache_ttl: int = 300
    required_audience: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AuthConfig":
        keycloak_url = os.getenv("KEYCLOAK_URL")
        realm = os.getenv("KEYCLOAK_REALM")
        client_id = os.getenv("KEYCLOAK_CLIENT_ID")
        client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")
        
        if not all([keycloak_url, realm, client_id, client_secret]):
            raise ValueError("Missing required Keycloak configuration")
        
        return cls(
            keycloak_url=keycloak_url.rstrip("/"),
            realm=realm,
            client_id=client_id,
            client_secret=client_secret,
            jwks_cache_ttl=int(os.getenv("JWKS_CACHE_TTL", "300")),
            required_audience=os.getenv("REQUIRED_AUDIENCE")
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

        try:
            timeout = httpx.Timeout(10.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Fetching JWKS from: {url}")
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                
                logger.debug(f"Successfully fetched JWKS from {url}")
                
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {url}: {e}")
            raise

        async with self._lock:
            self._cache[url] = {"data": data, "ts": now}

        return data

_JWKS = _JWKSCache()

class ExternalAuthService:
    """Authentication service for external STT deployment"""
    
    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig.from_env()
        self._oidc_config = None
        self._jwks_uri = None
    
    async def _get_oidc_config(self) -> Dict[str, Any]:
        """Get OIDC configuration from Keycloak"""
        if self._oidc_config:
            return self._oidc_config
            
        discovery_url = f"{self.config.keycloak_url}/realms/{self.config.realm}/.well-known/openid-configuration"
        
        try:
            timeout = httpx.Timeout(10.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Fetching OIDC config from: {discovery_url}")
                r = await client.get(discovery_url)
                r.raise_for_status()
                self._oidc_config = r.json()
                self._jwks_uri = self._oidc_config["jwks_uri"]
                
                logger.info(f"✅ OIDC configuration loaded for realm: {self.config.realm}")
                return self._oidc_config
                
        except Exception as e:
            logger.error(f"❌ OIDC discovery failed for {discovery_url}: {e}")
            raise HTTPException(status_code=503, detail=f"Authentication service unavailable: {e}")

    async def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token from Keycloak"""
        if not token:
            raise HTTPException(status_code=401, detail="Missing authentication token")

        try:
            # Get OIDC configuration
            oidc_config = await self._get_oidc_config()
            issuer = oidc_config["issuer"]
            jwks_uri = oidc_config["jwks_uri"]
            
            # Verify token using JWKS
            jwk_client = PyJWKClient(jwks_uri)
            signing_key = jwk_client.get_signing_key_from_jwt(token).key

            # Decode and verify token
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "RS384", "RS512"],
                audience=self.config.required_audience if self.config.required_audience else None,
                issuer=issuer,
                options={"verify_aud": bool(self.config.required_audience)}
            )
            
            logger.debug(f"✅ Token verified for user: {decoded.get('sub', 'unknown')}")
            return decoded

        except InvalidAudienceError as e:
            logger.warning(f"Invalid token audience: {e}")
            raise HTTPException(status_code=403, detail="Invalid token audience")
        except InvalidSignatureError as e:
            logger.warning(f"Invalid token signature: {e}")
            raise HTTPException(status_code=401, detail="Invalid token signature")
        except InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise HTTPException(status_code=401, detail="Token verification failed")

    async def get_service_token(self) -> str:
        """Get service-to-service token for calling orchestrator"""
        token_url = f"{self.config.keycloak_url}/realms/{self.config.realm}/protocol/openid-connect/token"
        
        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": "stt:notify orchestrator:webhook"
            }
            
            timeout = httpx.Timeout(10.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                access_token = token_data["access_token"]
                
                logger.debug("✅ Service token obtained successfully")
                return access_token
                
        except Exception as e:
            logger.error(f"❌ Failed to get service token: {e}")
            raise HTTPException(status_code=503, detail="Failed to obtain service authentication")

# Global auth service
_auth_service: Optional[ExternalAuthService] = None

def get_auth_service() -> ExternalAuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = ExternalAuthService()
    return _auth_service

# FastAPI Dependencies
async def require_user_auth(credentials = Depends(security)) -> Dict[str, Any]:
    """Require user authentication for STT endpoints"""
    auth_service = get_auth_service()
    return await auth_service.verify_token(credentials.credentials)

async def require_service_auth(credentials = Depends(security)) -> Dict[str, Any]:
    """Require service authentication (for orchestrator calls)"""
    auth_service = get_auth_service()
    token_data = await auth_service.verify_token(credentials.credentials)
    
    # Verify it's a service token (has client_credentials grant or service scope)
    if not (token_data.get("typ") == "Bearer" or "service" in token_data.get("scope", "")):
        logger.warning(f"Non-service token used for service endpoint: {token_data.get('sub')}")
    
    return token_data

def extract_user_id(auth_data: Dict[str, Any]) -> str:
    """Extract user ID from authentication data"""
    return auth_data.get("sub") or auth_data.get("user_id", "unknown")

def extract_client_id(auth_data: Dict[str, Any]) -> str:
    """Extract client ID from authentication data"""
    return auth_data.get("client_id") or auth_data.get("azp", "unknown")

async def validate_websocket_token(token: str) -> Dict[str, Any]:
    """Validate WebSocket token (if needed for streaming)"""
    auth_service = get_auth_service()
    return await auth_service.verify_token(token)

# Health check for auth service
async def test_auth_connectivity() -> Dict[str, Any]:
    """Test Keycloak connectivity"""
    try:
        auth_service = get_auth_service()
        await auth_service._get_oidc_config()
        return {"auth_service": "healthy", "keycloak": "connected"}
    except Exception as e:
        return {"auth_service": "unhealthy", "error": str(e)}