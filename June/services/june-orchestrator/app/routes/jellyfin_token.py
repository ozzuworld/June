"""Jellyfin SSO Token Exchange Endpoint

This endpoint allows mobile apps to exchange Keycloak tokens for Jellyfin session tokens.
Mobile apps authenticate with Keycloak first, then call this endpoint to get a Jellyfin token.
"""
import logging
import sys
from fastapi import APIRouter, HTTPException, Header
import httpx

# Add shared module to path for auth
sys.path.insert(0, '/app')
from shared.auth import require_user_auth, extract_user_id, AuthError

from ..config import config
from ..models.responses import JellyfinTokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jellyfin")


async def authenticate_jellyfin_user(username: str, password: str) -> dict:
    """
    Authenticate user with Jellyfin and create a session.

    For SSO users, this uses a service password that's configured in the backend.
    All SSO users should have this password set when they're created.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Authenticate as the user to get their token
            auth_response = await client.post(
                f"{config.jellyfin.base_url}/Users/AuthenticateByName",
                json={
                    "Username": username,
                    "Pw": password
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": 'MediaBrowser Client="June Mobile", Device="Mobile App", DeviceId="june-mobile", Version="1.0.0"'
                }
            )

            if auth_response.status_code == 401:
                # User exists but password is wrong - might not be an SSO user
                # or password wasn't set during SSO user creation
                raise HTTPException(
                    status_code=401,
                    detail="User authentication failed. SSO users must be created with proper credentials."
                )

            if auth_response.status_code != 200:
                logger.error(f"Jellyfin user auth failed: {auth_response.status_code} - {auth_response.text}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to authenticate with Jellyfin"
                )

            auth_data = auth_response.json()

            logger.info(f"Successfully authenticated Jellyfin user: {username}")

            return {
                "AccessToken": auth_data["AccessToken"],
                "User": {
                    "Id": auth_data["User"]["Id"],
                    "Name": auth_data["User"]["Name"]
                },
                "ServerId": auth_data["ServerId"]
            }

    except httpx.RequestError as e:
        logger.error(f"Jellyfin connection error: {e}")
        raise HTTPException(status_code=503, detail="Jellyfin service unavailable")


@router.post("/token", response_model=JellyfinTokenResponse)
async def exchange_token_for_jellyfin(
    authorization: str = Header(None)
) -> JellyfinTokenResponse:
    """
    Exchange Keycloak token for Jellyfin session token.

    This endpoint is designed for mobile apps that:
    1. Authenticate with Keycloak and obtain a Bearer token
    2. Call this endpoint with the Keycloak token
    3. Receive a Jellyfin access token to use with Jellyfin API

    The browser-based SSO flow (https://tv.ozzu.world/sso/OID/start/keycloak)
    doesn't work for native mobile apps, so this provides an alternative.

    Args:
        authorization: Bearer token from Keycloak (from Authorization header)

    Returns:
        JellyfinTokenResponse with access_token, user_id, server_id

    Raises:
        401: Invalid or missing Keycloak token
        404: User not found in Jellyfin
        500: Jellyfin authentication error
        503: Jellyfin service unavailable
    """
    try:
        # Validate Keycloak token and extract user info
        auth_data = await require_user_auth(authorization)
        user_email = auth_data.get("email")
        username = auth_data.get("preferred_username") or user_email

        if not username:
            raise HTTPException(
                status_code=400,
                detail="Token missing required claims (email or preferred_username)"
            )

        logger.info(f"Token exchange request for user: {username}")

        # Authenticate with Jellyfin using SSO user password
        # SSO users must have this password set when they're created
        session_data = await authenticate_jellyfin_user(
            username=username,
            password=config.jellyfin.sso_user_password
        )

        logger.info(f"Successfully created Jellyfin session for user: {username}")

        return JellyfinTokenResponse(
            access_token=session_data["AccessToken"],
            user_id=session_data["User"]["Id"],
            server_id=session_data["ServerId"],
            username=session_data["User"]["Name"]
        )

    except AuthError as e:
        logger.warning(f"Authentication failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in token exchange: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
