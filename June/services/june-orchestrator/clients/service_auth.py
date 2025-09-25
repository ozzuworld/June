# services/june-orchestrator/clients/service_auth.py
import os
import httpx
from typing import Dict, Any

class ServiceAuthClient:
    def __init__(self):
        self.keycloak_url = os.getenv("KEYCLOAK_URL")
        self.realm = os.getenv("KEYCLOAK_REALM", "june")
        self.client_id = os.getenv("KEYCLOAK_CLIENT_ID") 
        self.client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")
        self._token_cache = {}
        
    async def get_service_token(self, service_name: str) -> str:
        """Get service token from Keycloak"""
        token_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": f"june-{service_name}",
            "client_secret": self.client_secret,
            "scope": "openid profile"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            return token_data["access_token"]
    
    async def make_authenticated_request(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> httpx.Response:
        """Make authenticated request to another service"""
        # Extract service name from URL or pass explicitly
        service_name = self._extract_service_name(url)
        token = await self.get_service_token(service_name)
        
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, **kwargs)