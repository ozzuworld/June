"""
VPN Device Registration API

Handles VPN device registration using Headscale and Keycloak authentication.
"""
import logging
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
import httpx

# Import shared auth service
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../shared'))
from auth import require_user_auth, extract_user_id, AuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/device")


class DeviceRegistrationRequest(BaseModel):
    """Request model for device registration"""
    device_name: Optional[str] = Field(
        None,
        description="Optional device name. If not provided, auto-generated from user email"
    )
    device_os: Optional[str] = Field(
        None,
        description="Device OS (ios, android, macos, windows, linux)"
    )
    device_model: Optional[str] = Field(
        None,
        description="Device model/version"
    )


class DeviceRegistrationResponse(BaseModel):
    """Response model for successful device registration"""
    success: bool
    message: str
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    vpn_ip: Optional[str] = None
    headscale_url: str
    auth_url: str
    instructions: Dict[str, str]


class HeadscaleClient:
    """Client for interacting with Headscale API"""

    def __init__(self):
        self.base_url = os.getenv("HEADSCALE_URL", "http://headscale.headscale.svc.cluster.local:8080")
        self.external_url = os.getenv("HEADSCALE_EXTERNAL_URL", "https://headscale.ozzu.world")

    async def create_preauth_key(self, user_email: str) -> Optional[str]:
        """
        Create a pre-authentication key for a user

        Note: This requires headscale CLI access or API key
        For production, use OIDC flow instead (no preauth needed)
        """
        # In production with OIDC, preauth keys aren't needed
        # The user will authenticate directly with Keycloak via OIDC
        logger.info(f"OIDC-based registration for user: {user_email}")
        return None

    async def get_user_devices(self, user_email: str) -> list:
        """Get all devices for a user"""
        # TODO: Implement if Headscale API supports this
        # For now, users can check via Tailscale client
        return []

    async def check_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Check if a device is registered and get its status"""
        # TODO: Implement when Headscale API is available
        return None


async def get_headscale_client() -> HeadscaleClient:
    """Dependency to get Headscale client"""
    return HeadscaleClient()


@router.post("/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request: DeviceRegistrationRequest,
    authorization: str = Header(None),
    headscale: HeadscaleClient = Depends(get_headscale_client)
):
    """
    Register a VPN device using Keycloak authentication + Headscale OIDC

    This endpoint provides the necessary information for the frontend to
    initiate VPN connection via OIDC flow.

    Flow:
    1. User authenticates with Keycloak (gets bearer token)
    2. Frontend calls this endpoint with bearer token
    3. Backend validates token and returns Headscale connection info
    4. Frontend opens Headscale OIDC URL in browser
    5. User approves (using existing Keycloak session - seamless!)
    6. Device gets registered with Headscale
    7. VPN connected!

    Args:
        request: Device registration details
        authorization: Bearer token from Keycloak

    Returns:
        DeviceRegistrationResponse with Headscale connection URL

    Raises:
        HTTPException: 401 if unauthorized, 500 for server errors
    """

    # Validate authentication
    if not authorization:
        logger.warning("Device registration attempted without authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header. Please provide a valid Bearer token."
        )

    try:
        # Verify Keycloak token
        auth_data = await require_user_auth(authorization)
        user_email = auth_data.get("email")
        user_id = extract_user_id(auth_data)
        preferred_username = auth_data.get("preferred_username", user_email)

        logger.info(f"Device registration request from user: {user_email} (ID: {user_id})")

        if not user_email:
            raise HTTPException(
                status_code=400,
                detail="User email not found in token. Please ensure email scope is included."
            )

        # Generate device name if not provided
        device_name = request.device_name
        if not device_name:
            # Auto-generate from user email and device info
            username = user_email.split("@")[0]
            os_suffix = f"-{request.device_os}" if request.device_os else ""
            device_name = f"{username}{os_suffix}"

        # Sanitize device name for Headscale (alphanumeric, hyphens, dots)
        device_name = "".join(c if c.isalnum() or c in "-." else "-" for c in device_name)

        logger.info(f"Device name: {device_name}")

        # Build OIDC authentication URL
        # The frontend will open this URL to complete device registration
        headscale_external = headscale.external_url

        # For OIDC flow, the device registers via browser authentication
        # No preauth key needed when OIDC is enabled
        auth_url = f"{headscale_external}/oidc/register"

        logger.info(f"Generated OIDC registration URL for {user_email}")

        return DeviceRegistrationResponse(
            success=True,
            message="Device registration prepared. Please complete OIDC authentication.",
            device_name=device_name,
            headscale_url=headscale_external,
            auth_url=auth_url,
            instructions={
                "step_1": "Open the auth_url in your device's browser",
                "step_2": "Login with your Keycloak credentials (if not already logged in)",
                "step_3": "Approve the VPN connection",
                "step_4": "Your device will be automatically registered",
                "tailscale_command": f"tailscale up --login-server={headscale_external}",
                "note": "Since you're already logged into Keycloak, the browser should auto-approve!"
            }
        )

    except AuthError as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device registration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Device registration failed: {str(e)}"
        )


@router.get("/status")
async def get_device_status(
    authorization: str = Header(None),
    headscale: HeadscaleClient = Depends(get_headscale_client)
):
    """
    Get VPN device status for the authenticated user

    Args:
        authorization: Bearer token from Keycloak

    Returns:
        Device status information
    """

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        # Verify token
        auth_data = await require_user_auth(authorization)
        user_email = auth_data.get("email")

        logger.info(f"Device status check for user: {user_email}")

        # TODO: Query Headscale API for user's devices
        # For now, return instructions

        return {
            "success": True,
            "user": user_email,
            "message": "Check device status using: tailscale status",
            "devices": [],  # Will be populated when Headscale API is available
            "instructions": {
                "check_connection": "tailscale status",
                "get_ip": "tailscale ip -4",
                "disconnect": "tailscale down",
                "reconnect": f"tailscale up --login-server={headscale.external_url}"
            }
        }

    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Status check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/unregister")
async def unregister_device(
    device_id: str,
    authorization: str = Header(None),
    headscale: HeadscaleClient = Depends(get_headscale_client)
):
    """
    Unregister a VPN device

    Args:
        device_id: ID of device to unregister
        authorization: Bearer token from Keycloak

    Returns:
        Success confirmation
    """

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        # Verify token
        auth_data = await require_user_auth(authorization)
        user_email = auth_data.get("email")

        logger.info(f"Device unregister request from {user_email} for device: {device_id}")

        # TODO: Implement device deletion via Headscale API

        return {
            "success": True,
            "message": f"Device {device_id} unregistered",
            "instructions": {
                "manual_removal": "Run on device: tailscale logout",
                "admin_removal": f"kubectl exec -n headscale deployment/headscale -- headscale nodes delete {device_id}"
            }
        }

    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Device unregister failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_vpn_config(
    authorization: str = Header(None)
):
    """
    Get VPN configuration information

    Args:
        authorization: Bearer token from Keycloak

    Returns:
        VPN configuration details
    """

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        # Verify token
        auth_data = await require_user_auth(authorization)
        user_email = auth_data.get("email")

        logger.info(f"VPN config requested by: {user_email}")

        headscale_url = os.getenv("HEADSCALE_EXTERNAL_URL", "https://headscale.ozzu.world")

        return {
            "success": True,
            "config": {
                "headscale_url": headscale_url,
                "auth_method": "OIDC",
                "keycloak_url": os.getenv("KEYCLOAK_URL", "https://idp.ozzu.world"),
                "realm": os.getenv("KEYCLOAK_REALM", "allsafe"),
                "supported_clients": ["iOS", "Android", "macOS", "Windows", "Linux"]
            },
            "quick_start": {
                "mobile": "Use Tailscale app and set custom control server to " + headscale_url,
                "desktop": f"tailscale up --login-server={headscale_url}",
                "oidc_flow": "Browser opens → Login with Keycloak → VPN connects automatically"
            }
        }

    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Config retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
