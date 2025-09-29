# June/services/june-orchestrator/service_auth.py
"""
Service-to-Service Authentication Module
Handles authentication between orchestrator and other microservices
"""

import os
import time
import asyncio
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


@dataclass
class ServiceToken:
    """Service authentication token with expiry tracking"""
    access_token: str
    expires_at: float
    token_type: str = "Bearer"
    
    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire soon"""
        return time.time() >= (self.expires_at - buffer_seconds)


class ServiceAuthClient:
    """
    Manages service-to-service authentication using OAuth2 Client Credentials flow
    """
    
    def __init__(self):
        self.keycloak_url = os.getenv("KEYCLOAK_URL", "https://idp.allsafe.world")
        self.realm = os.getenv("KEYCLOAK_REALM", "allsafe")
        self.client_id = os.getenv("SERVICE_ACCOUNT_CLIENT_ID")
        self.client_secret = os.getenv("SERVICE_ACCOUNT_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            logger.warning("⚠️ Service account credentials not configured")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"✅ Service auth configured with client: {self.client_id}")
        
        # Token cache
        self._token_cache: Optional[ServiceToken] = None
        self._token_lock = asyncio.Lock()
        
        # HTTP client settings
        self.timeout = httpx.Timeout(10.0, connect=5.0)
    
    async def get_service_token(self, force_refresh: bool = False) -> str:
        """
        Get a valid service token, refreshing if necessary
        
        Args:
            force_refresh: Force token refresh even if cached token is valid
            
        Returns:
            Valid access token string
        """
        if not self.enabled:
            raise RuntimeError("Service authentication not configured")
        
        # Check cache
        if not force_refresh and self._token_cache and not self._token_cache.is_expired():
            logger.debug("Using cached service token")
            return self._token_cache.access_token
        
        # Refresh token
        async with self._token_lock:
            # Double-check after acquiring lock
            if not force_refresh and self._token_cache and not self._token_cache.is_expired():
                return self._token_cache.access_token
            
            logger.info("🔄 Refreshing service token...")
            token = await self._request_new_token()
            self._token_cache = token
            
            return token.access_token
    
    async def _request_new_token(self) -> ServiceToken:
        """Request a new service token from Keycloak"""
        token_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "stt:transcribe stt:read tts:synthesize tts:read"
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug(f"Requesting service token from: {token_url}")
                
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                
                # Calculate expiry time
                expires_in = token_data.get("expires_in", 3600)
                expires_at = time.time() + expires_in
                
                access_token = token_data["access_token"]
                
                logger.info(f"✅ Service token obtained (expires in {expires_in}s)")
                
                return ServiceToken(
                    access_token=access_token,
                    expires_at=expires_at,
                    token_type=token_data.get("token_type", "Bearer")
                )
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Failed to get service token: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"Service authentication failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"❌ Service token request failed: {e}")
            raise RuntimeError(f"Service authentication failed: {e}")
    
    async def get_auth_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers with valid service authentication
        
        Returns:
            Dictionary of headers including Authorization
        """
        token = await self.get_service_token()
        
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": "june-orchestrator/3.1.0",
            "X-Service-Source": "june-orchestrator"
        }
    
    async def test_authentication(self) -> Dict[str, Any]:
        """
        Test service authentication
        
        Returns:
            Status dictionary with authentication details
        """
        if not self.enabled:
            return {
                "enabled": False,
                "error": "Service authentication not configured"
            }
        
        try:
            token = await self.get_service_token(force_refresh=True)
            
            # Decode token (without verification) to inspect claims
            import jwt
            decoded = jwt.decode(token, options={"verify_signature": False})
            
            return {
                "enabled": True,
                "authenticated": True,
                "client_id": decoded.get("azp") or decoded.get("client_id"),
                "scopes": decoded.get("scope", "").split(),
                "expires_at": decoded.get("exp"),
                "issued_at": decoded.get("iat")
            }
            
        except Exception as e:
            logger.error(f"❌ Service auth test failed: {e}")
            return {
                "enabled": True,
                "authenticated": False,
                "error": str(e)
            }


# Global service auth client
_service_auth_client: Optional[ServiceAuthClient] = None


def get_service_auth_client() -> ServiceAuthClient:
    """Get global service authentication client"""
    global _service_auth_client
    
    if _service_auth_client is None:
        _service_auth_client = ServiceAuthClient()
    
    return _service_auth_client


async def get_service_token() -> str:
    """Convenience function to get service token"""
    client = get_service_auth_client()
    return await client.get_service_token()


async def get_service_auth_headers() -> Dict[str, str]:
    """Convenience function to get auth headers"""
    client = get_service_auth_client()
    return await client.get_auth_headers()