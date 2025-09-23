# June/services/june-tts-proxy/shared/auth_service.py
# Shared authentication module for service-to-service communication

import os
import time
import httpx
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger(__name__)

@dataclass
class ServiceCredentials:
    client_id: str
    client_secret: str
    keycloak_url: str
    realm: str = "june"

@dataclass
class AccessToken:
    token: str
    expires_at: float
    token_type: str = "Bearer"
    
    @property
    def is_expired(self) -> bool:
        # Add 30 second buffer
        return time.time() >= (self.expires_at - 30)

class ServiceAuthClient:
    """Handles service-to-service authentication using OAuth 2.0 Client Credentials"""
    
    def __init__(self, credentials: ServiceCredentials):
        self.credentials = credentials
        self._token: Optional[AccessToken] = None
        self._lock = Lock()
        
    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if needed"""
        with self._lock:
            if self._token and not self._token.is_expired:
                return self._token.token
            
            # Token expired or doesn't exist, get a new one
            await self._refresh_token()
            return self._token.token
    
    async def _refresh_token(self):
        """Get a new access token from Keycloak"""
        token_url = f"{self.credentials.keycloak_url}/realms/{self.credentials.realm}/protocol/openid-connect/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret,
            "scope": "openid profile"
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0
                )
                response.raise_for_status()
                
                token_data = response.json()
                expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
                
                self._token = AccessToken(
                    token=token_data["access_token"],
                    expires_at=time.time() + expires_in,
                    token_type=token_data.get("token_type", "Bearer")
                )
                
                logger.info(f"Successfully obtained access token for {self.credentials.client_id}")
                
            except Exception as e:
                logger.error(f"Failed to get access token: {e}")
                raise
    
    async def make_authenticated_request(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> httpx.Response:
        """Make an HTTP request with automatic token injection"""
        token = await self.get_access_token()
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, headers=headers, **kwargs)

# Factory function to create auth client from environment
def create_service_auth_client(service_name: str) -> ServiceAuthClient:
    """Create an auth client for the current service"""
    
    # Environment variables for each service
    client_id = os.getenv(f"{service_name.upper()}_CLIENT_ID")
    client_secret = os.getenv(f"{service_name.upper()}_CLIENT_SECRET")
    keycloak_url = os.getenv("KC_BASE_URL", "http://localhost:8080")
    realm = os.getenv("KC_REALM", "june")
    
    if not client_id or not client_secret:
        raise ValueError(f"Missing credentials for service {service_name}. Need {service_name.upper()}_CLIENT_ID and {service_name.upper()}_CLIENT_SECRET")
    
    credentials = ServiceCredentials(
        client_id=client_id,
        client_secret=client_secret,
        keycloak_url=keycloak_url,
        realm=realm
    )
    
    return ServiceAuthClient(credentials)

# JWT validation for incoming requests from other services
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import httpx

security = HTTPBearer()

class ServiceTokenValidator:
    def __init__(self, keycloak_url: str, realm: str = "june"):
        self.keycloak_url = keycloak_url
        self.realm = realm
        self._jwks_cache = None
        self._jwks_cache_time = 0
    
    async def get_jwks(self) -> Dict[str, Any]:
        """Get JWT public keys from Keycloak (with caching)"""
        now = time.time()
        
        # Cache for 1 hour
        if self._jwks_cache and (now - self._jwks_cache_time) < 3600:
            return self._jwks_cache
        
        jwks_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/certs"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10.0)
            response.raise_for_status()
            
            self._jwks_cache = response.json()
            self._jwks_cache_time = now
            
            return self._jwks_cache
    
    async def validate_service_token(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> Dict[str, Any]:
        """Validate JWT token from another service"""
        try:
            # Get public keys
            jwks = await self.get_jwks()
            
            # Decode and validate token
            header = jwt.get_unverified_header(credentials.credentials)
            key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
            
            # Convert JWK to PEM format
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            
            payload = jwt.decode(
                credentials.credentials,
                public_key,
                algorithms=["RS256"],
                audience="account",  # Keycloak default audience
                issuer=f"{self.keycloak_url}/realms/{self.realm}"
            )
            
            # Check if it's a service account token
            if payload.get("typ") != "Bearer":
                raise HTTPException(status_code=401, detail="Invalid token type")
            
            # Extract service identity
            client_id = payload.get("azp") or payload.get("client_id")
            if not client_id:
                raise HTTPException(status_code=401, detail="No client ID in token")
            
            return {
                "client_id": client_id,
                "subject": payload.get("sub"),
                "scopes": payload.get("scope", "").split(),
                "expires_at": payload.get("exp"),
                "payload": payload
            }
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            raise HTTPException(status_code=401, detail="Token validation failed")

# Global validator instance
def get_token_validator():
    return ServiceTokenValidator(
        keycloak_url=os.getenv("KC_BASE_URL", "http://localhost:8080"),
        realm=os.getenv("KC_REALM", "june")
    )

# Dependency for protecting service endpoints
async def require_service_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """FastAPI dependency to require service authentication"""
    validator = get_token_validator()
    return await validator.validate_service_token(credentials)