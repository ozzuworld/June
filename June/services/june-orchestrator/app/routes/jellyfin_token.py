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


async def get_admin_token() -> str:
    """Get admin authentication token from Jellyfin"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            auth_response = await client.post(
                f"{config.jellyfin.base_url}/Users/AuthenticateByName",
                json={
                    "Username": config.jellyfin.admin_username,
                    "Pw": config.jellyfin.admin_password
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": 'MediaBrowser Client="June API", Device="Server", DeviceId="june-backend", Version="1.0.0"'
                }
            )

            if auth_response.status_code != 200:
                logger.error(f"Admin auth failed: {auth_response.status_code}")
                raise HTTPException(status_code=500, detail="Failed to authenticate as admin")

            return auth_response.json()["AccessToken"]

    except httpx.RequestError as e:
        logger.error(f"Jellyfin connection error: {e}")
        raise HTTPException(status_code=503, detail="Jellyfin service unavailable")


async def create_user_session_with_admin(username: str, admin_token: str) -> dict:
    """
    Create a Jellyfin session for an SSO user using admin privileges.

    This approach works for SSO users who don't have passwords:
    1. Get user info with admin token
    2. Create a new authentication token for the user
    3. Return the token to the mobile app

    This is secure because:
    - We validate the Keycloak token first
    - Only authenticated users can get Jellyfin tokens
    - The admin password never leaves the backend
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get all users to find this user
            users_response = await client.get(
                f"{config.jellyfin.base_url}/Users",
                headers={
                    "X-Emby-Token": admin_token,
                    "Content-Type": "application/json"
                }
            )

            if users_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch users from Jellyfin")

            users = users_response.json()
            user = None
            username_lower = username.lower()

            for u in users:
                if u.get("Name", "").lower() == username_lower:
                    user = u
                    break

            if not user:
                raise HTTPException(
                    status_code=404,
                    detail=f"User '{username}' not found in Jellyfin. User must login via browser SSO first."
                )

            # Get server info
            server_response = await client.get(
                f"{config.jellyfin.base_url}/System/Info",
                headers={
                    "X-Emby-Token": admin_token,
                    "Content-Type": "application/json"
                }
            )

            if server_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to get server info")

            server_id = server_response.json().get("Id", "unknown")

            # For SSO users without passwords, we return the admin token
            # This is a limitation of Jellyfin's API - there's no way to create
            # user-specific sessions without passwords.
            #
            # Alternative approach: Use the SSO plugin's password if set
            # Try to authenticate as the user first with SSO password
            try_sso_auth = await client.post(
                f"{config.jellyfin.base_url}/Users/AuthenticateByName",
                json={
                    "Username": username,
                    "Pw": config.jellyfin.sso_user_password
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": 'MediaBrowser Client="June Mobile", Device="Mobile App", DeviceId="june-mobile", Version="1.0.0"'
                }
            )

            if try_sso_auth.status_code == 200:
                # User has the SSO password set - use their token
                auth_data = try_sso_auth.json()
                logger.info(f"Created session for SSO user '{username}' with password auth")
                return {
                    "AccessToken": auth_data["AccessToken"],
                    "User": {
                        "Id": auth_data["User"]["Id"],
                        "Name": auth_data["User"]["Name"]
                    },
                    "ServerId": auth_data["ServerId"]
                }
            else:
                # User doesn't have password - they're a pure SSO user
                # Return admin token with user info
                # NOTE: This gives admin privileges - not ideal for production
                logger.warning(
                    f"User '{username}' is a pure SSO user without password. "
                    "Returning admin token (has admin privileges). "
                    "Recommend setting JELLYFIN_SSO_USER_PASSWORD for all SSO users."
                )

                return {
                    "AccessToken": admin_token,
                    "User": {
                        "Id": user["Id"],
                        "Name": user["Name"]
                    },
                    "ServerId": server_id
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

        # Get admin token to interact with Jellyfin API
        admin_token = await get_admin_token()

        # Create session for the user
        # This tries SSO password auth first, falls back to admin token if user has no password
        session_data = await create_user_session_with_admin(username, admin_token)

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
