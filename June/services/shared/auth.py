# June/services/shared/auth.py
import os
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional
import logging

import httpx
import jwt
from jwt import PyJWKClient, InvalidTokenError, InvalidSignatureError, InvalidAudienceError

logger = logging.getLogger(__name__)

class AuthError(Exception):
    pass


@dataclass
class AuthConfig:
    keycloak_url: str
    realm: str
    jwks_cache_ttl: int = 300
    required_audience: Optional[str] = None
    jwt_signing_key: Optional[str] = None
    external_issuer: Optional[str] = None  # For token validation with external issuer

    @classmethod
    def from_env(cls) -> "AuthConfig":
        # Primary URLs for internal communication
        internal_url = os.getenv("KEYCLOAK_URL") or os.getenv("KC_BASE_URL")
        realm = os.getenv("KEYCLOAK_REALM") or os.getenv("KC_REALM")
        
        # External URLs for public token validation
        external_url = os.getenv("EXTERNAL_KEYCLOAK_URL")
        external_issuer = os.getenv("EXTERNAL_ISSUER")
        
        if not internal_url:
            raise AuthError("KEYCLOAK_URL (or KC_BASE_URL) is not set")
        if not realm:
            raise AuthError("KEYCLOAK_REALM (or KC_REALM) is not set")

        return cls(
            keycloak_url=internal_url.rstrip("/"),
            realm=realm,
            jwks_cache_ttl=int(os.getenv("JWKS_CACHE_TTL", "300")),
            required_audience=os.getenv("REQUIRED_AUDIENCE"),
            jwt_signing_key=os.getenv("JWT_SIGNING_KEY"),
            external_issuer=external_issuer,
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


class AuthService:
    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig.from_env()

    async def _fetch_oidc_config(self, base_url: Optional[str] = None) -> Dict[str, Any]:
        """Fetch OIDC configuration from Keycloak"""
        keycloak_url = base_url or self.config.keycloak_url
        discovery_url = f"{keycloak_url}/realms/{self.config.realm}/.well-known/openid-configuration"
        
        try:
            timeout = httpx.Timeout(10.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Fetching OIDC config from: {discovery_url}")
                r = await client.get(discovery_url)
                r.raise_for_status()
                config = r.json()
                
                logger.debug(f"Successfully fetched OIDC config from {discovery_url}")
                return config
                
        except Exception as e:
            logger.error(f"OIDC discovery failed for {discovery_url}: {e}")
            raise AuthError(f"OIDC discovery failed: {e}") from e

    async def _fetch_jwks(self, jwks_uri: str) -> Dict[str, Any]:
        return await _JWKS.get(jwks_uri, self.config.jwks_cache_ttl)

    async def verify_bearer(self, token: str) -> Dict[str, Any]:
        """Verify a bearer token using OIDC discovery"""
        if not token:
            raise AuthError("Missing bearer token")

        # Extract issuer from token to determine which endpoint to use
        try:
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            token_issuer = unverified_payload.get("iss", "")
            logger.debug(f"Token issuer: {token_issuer}")
        except Exception as e:
            logger.warning(f"Could not extract issuer from token: {e}")
            token_issuer = ""

        # Determine which Keycloak URL to use based on token issuer
        config_url = None
        
        # If token has external issuer, try external URL first
        if self.config.external_issuer and token_issuer == self.config.external_issuer:
            external_url = os.getenv("EXTERNAL_KEYCLOAK_URL")
            if external_url:
                config_url = external_url
                logger.debug("Using external Keycloak URL for token validation")

        # Try to get OIDC config, with fallback to internal URL
        oidc_config = None
        last_error = None
        
        urls_to_try = []
        if config_url:
            urls_to_try.append(config_url)
        urls_to_try.append(self.config.keycloak_url)
        
        for url in urls_to_try:
            try:
                oidc_config = await self._fetch_oidc_config(url)
                logger.debug(f"Successfully got OIDC config from {url}")
                break
            except Exception as e:
                logger.warning(f"Failed to get OIDC config from {url}: {e}")
                last_error = e
                continue
        
        if not oidc_config:
            raise AuthError(f"Could not fetch OIDC config from any URL. Last error: {last_error}")

        issuer = oidc_config["issuer"]
        jwks_uri = oidc_config["jwks_uri"]

        # Rewrite external URLs to internal service URLs when inside K8s
        # This handles cases where OIDC discovery returns external URLs
        # but we're running inside the cluster
        if "idp.ozzu.world" in jwks_uri or "idp.ozzu.world" in issuer:
            # Replace external URL with internal service URL
            internal_keycloak = self.config.keycloak_url
            jwks_uri = jwks_uri.replace("http://idp.ozzu.world:8080", internal_keycloak)
            jwks_uri = jwks_uri.replace("https://idp.ozzu.world", internal_keycloak)
            logger.debug(f"Rewrote external JWKS URI to internal: {jwks_uri}")

        logger.debug(f"Using issuer: {issuer}, JWKS URI: {jwks_uri}")

        try:
            # Fetch JWKS using httpx (better timeout handling)
            jwks_data = await self._fetch_jwks(jwks_uri)

            # Find the signing key manually
            signing_key = None
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                raise AuthError("Token missing 'kid' header")

            for key in jwks_data.get("keys", []):
                if key.get("kid") == kid:
                    # Convert JWK to RSA key using cryptography library
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric import rsa
                    from cryptography.hazmat.backends import default_backend
                    import base64

                    # Extract RSA components from JWK
                    n = int.from_bytes(
                        base64.urlsafe_b64decode(key['n'] + '=='),
                        byteorder='big'
                    )
                    e = int.from_bytes(
                        base64.urlsafe_b64decode(key['e'] + '=='),
                        byteorder='big'
                    )

                    # Create RSA public key
                    public_numbers = rsa.RSAPublicNumbers(e, n)
                    signing_key = public_numbers.public_key(default_backend())
                    break

            if not signing_key:
                raise AuthError(f"No matching key found for kid: {kid}")

            options = {"verify_aud": bool(self.config.required_audience)}
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                audience=self.config.required_audience if self.config.required_audience else None,
                issuer=issuer,
                options=options,
            )

            logger.debug(f"Successfully validated token for user: {decoded.get('sub', 'unknown')}")
            return decoded

        except InvalidAudienceError as e:
            logger.warning(f"Token audience invalid: {e}")
            raise AuthError(f"Token audience invalid: {e}") from e
        except InvalidSignatureError as e:
            logger.warning(f"Token signature invalid: {e}")
            raise AuthError(f"Token signature invalid: {e}") from e
        except InvalidTokenError as e:
            logger.warning(f"Token invalid: {e}")
            raise AuthError(f"Token invalid: {e}") from e
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise AuthError(f"Token verification error: {e}") from e


# Global auth service instance
_auth_service: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


# FastAPI dependencies
async def require_user_auth(token: str = None) -> Dict[str, Any]:
    """FastAPI dependency for user authentication"""
    if not token:
        raise AuthError("No authorization token provided")
    
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    
    auth_service = get_auth_service()
    return await auth_service.verify_bearer(token)


async def require_service_auth(token: str = None) -> Dict[str, Any]:
    """FastAPI dependency for service-to-service authentication"""
    # For now, use the same validation as user auth
    # In the future, you might want different validation for service tokens
    return await require_user_auth(token)


async def optional_user_auth(token: str = None) -> Optional[Dict[str, Any]]:
    """FastAPI dependency for optional user authentication"""
    if not token:
        return None
    
    try:
        return await require_user_auth(token)
    except AuthError:
        return None


async def validate_websocket_token(token: str) -> Dict[str, Any]:
    """Validate a WebSocket token"""
    return await require_user_auth(token)


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
    scopes = auth_data.get("scope", "").split()
    return scope in scopes


async def test_keycloak_connection() -> Dict[str, Any]:
    """Test function to debug Keycloak connectivity"""
    auth_service = get_auth_service()
    config = auth_service.config
    
    result = {
        "config": {
            "keycloak_url": config.keycloak_url,
            "realm": config.realm,
            "external_issuer": config.external_issuer,
        },
        "tests": {}
    }
    
    # Test internal OIDC discovery
    try:
        oidc_config = await auth_service._fetch_oidc_config()
        result["tests"]["internal_oidc"] = {
            "success": True,
            "issuer": oidc_config.get("issuer"),
            "jwks_uri": oidc_config.get("jwks_uri"),
        }
    except Exception as e:
        result["tests"]["internal_oidc"] = {
            "success": False,
            "error": str(e)
        }
    
    # Test external OIDC discovery if configured
    external_url = os.getenv("EXTERNAL_KEYCLOAK_URL")
    if external_url:
        try:
            oidc_config = await auth_service._fetch_oidc_config(external_url)
            result["tests"]["external_oidc"] = {
                "success": True,
                "issuer": oidc_config.get("issuer"),
                "jwks_uri": oidc_config.get("jwks_uri"),
            }
        except Exception as e:
            result["tests"]["external_oidc"] = {
                "success": False,
                "error": str(e)
            }
    
    return result