# services/shared/auth.py
import os
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import jwt
from jwt import PyJWKClient, InvalidTokenError, InvalidSignatureError, InvalidAudienceError


class AuthError(Exception):
    pass


@dataclass
class AuthConfig:
    keycloak_url: str
    realm: str
    jwks_cache_ttl: int = 300
    required_audience: Optional[str] = None
    jwt_signing_key: Optional[str] = None  # optional symmetric key if you use internal JWTs

    @classmethod
    def from_env(cls) -> "AuthConfig":
        url = os.getenv("KEYCLOAK_URL") or os.getenv("KC_BASE_URL")
        realm = os.getenv("KEYCLOAK_REALM") or os.getenv("KC_REALM")
        if not url:
            raise AuthError("KEYCLOAK_URL (or KC_BASE_URL) is not set")
        if not realm:
            raise AuthError("KEYCLOAK_REALM (or KC_REALM) is not set")

        return cls(
            keycloak_url=url.rstrip("/"),
            realm=realm,
            jwks_cache_ttl=int(os.getenv("JWKS_CACHE_TTL", "300")),
            required_audience=os.getenv("REQUIRED_AUDIENCE"),
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

    async def _fetch_jwks(self, jwks_uri: str) -> Dict[str, Any]:
        return await _JWKS.get(jwks_uri, self.config.jwks_cache_ttl)

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
            # Use JWKS to pick the signing key
            jwk_client = PyJWKClient(jwks_uri)
            signing_key = jwk_client.get_signing_key_from_jwt(token).key

            options = {"verify_aud": bool(self.config.required_audience)}
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                audience=self.config.required_audience if self.config.required_audience else None,
                issuer=issuer,
                options=options,
            )
            return decoded

        except InvalidAudienceError as e:
            raise AuthError(f"Token audience invalid: {e}") from e
        except InvalidSignatureError as e:
            raise AuthError(f"Token signature invalid: {e}") from e
        except InvalidTokenError as e:
            raise AuthError(f"Token invalid: {e}") from e
        except Exception as e:
            raise AuthError(f"Token verification error: {e}") from e
