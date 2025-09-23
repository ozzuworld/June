import os
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

security = HTTPBearer(auto_error=False)


def _get_jwt_config() -> tuple[str, Optional[str], Optional[str]]:
    secret = os.getenv("JWT_SIGNING_KEY")
    if not secret:
        raise RuntimeError("JWT_SIGNING_KEY is required")
    issuer = os.getenv("JWT_ISSUER")
    audience = os.getenv("JWT_AUDIENCE")
    return secret, issuer, audience


def _verify_token(token: str) -> Dict[str, Any]:
    secret, issuer, audience = _get_jwt_config()
    options = {"require": ["exp"], "verify_signature": True}
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],  # Switch to RS256 + JWKS for Keycloak if you prefer
            issuer=issuer if issuer else None,
            audience=audience if audience else None,
            options=options,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e
    return payload


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not creds or not creds.scheme.lower() == "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = creds.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    claims = _verify_token(token)
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Token missing sub claim")
    # Return a simple user dict; expand as needed
    return {"sub": claims["sub"], "email": claims.get("email"), "roles": claims.get("roles", [])}
