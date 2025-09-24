# shared/auth.py
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
import httpx
import jwt
from functools import lru_cache

security = HTTPBearer()

class AuthConfig:
    def __init__(self):
        self.keycloak_url = os.getenv("KEYCLOAK_URL")
        self.realm = os.getenv("KEYCLOAK_REALM", "june")
        self.jwks_cache_ttl = 3600
        
    @lru_cache(maxsize=1)
    async def get_jwks(self):
        # Implement JWKS caching
        pass

class AuthService:
    def __init__(self, config: AuthConfig):
        self.config = config
        
    async def validate_user_token(self, token: str) -> dict:
        # Unified user token validation
        pass
        
    async def validate_service_token(self, token: str) -> dict:
        # Unified service token validation  
        pass

# Use across all services
async def require_user_auth(credentials = Depends(security)) -> dict:
    auth_service = get_auth_service()
    return await auth_service.validate_user_token(credentials.credentials)