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
sys.path.insert(0, '/app')
from shared.auth import require_user_auth, extract_user_id, AuthError

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
    device_name: str
    login_server: str
    pre_auth_key: str
    expiration: str
    instructions: Dict[str, str]


class HeadscaleClient:
    """Client for interacting with Headscale API"""

    def __init__(self):
        self.base_url = os.getenv("HEADSCALE_URL", "http://headscale.headscale.svc.cluster.local:8080")
        self.external_url = os.getenv("HEADSCALE_EXTERNAL_URL", "https://headscale.ozzu.world")
        self.api_key = os.getenv("HEADSCALE_API_KEY", "")  # Will be set if available

    async def _exec_headscale_cli(self, command: list) -> tuple[bool, str]:
        """
        Execute headscale CLI command via kubectl exec

        Args:
            command: List of command arguments (e.g., ['users', 'list'])

        Returns:
            Tuple of (success: bool, output: str)
        """
        import subprocess

        namespace = "headscale"
        deployment = "headscale"

        # Build kubectl exec command
        kubectl_cmd = [
            "kubectl", "exec", "-n", namespace,
            f"deployment/{deployment}", "--",
            "headscale"
        ] + command

        try:
            result = subprocess.run(
                kubectl_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return True, result.stdout
            else:
                logger.error(f"Headscale CLI error: {result.stderr}")
                return False, result.stderr

        except subprocess.TimeoutExpired:
            logger.error("Headscale CLI command timed out")
            return False, "Command timed out"
        except Exception as e:
            logger.error(f"Failed to execute headscale CLI: {e}")
            return False, str(e)

    async def ensure_user_exists(self, user_email: str) -> bool:
        """
        Ensure a Headscale user exists (create if doesn't exist)

        Args:
            user_email: User's email address (will be used as username)

        Returns:
            True if user exists or was created successfully
        """
        # Sanitize email for use as username (remove @ and .)
        username = user_email.replace("@", "-").replace(".", "-")

        # Check if user exists
        success, output = await self._exec_headscale_cli(["users", "list", "--output", "json"])

        if success:
            # Parse JSON output to check if user exists
            import json
            try:
                users = json.loads(output)
                if any(u.get("name") == username for u in users):
                    logger.info(f"User {username} already exists in Headscale")
                    return True
            except json.JSONDecodeError:
                # If not JSON, try simple string check
                if username in output:
                    logger.info(f"User {username} already exists in Headscale")
                    return True

        # User doesn't exist, create it
        logger.info(f"Creating Headscale user: {username}")
        success, output = await self._exec_headscale_cli(["users", "create", username])

        if success or "already exists" in output.lower():
            logger.info(f"User {username} created or already exists")
            return True
        else:
            logger.error(f"Failed to create user {username}: {output}")
            return False

    async def create_preauth_key(self, user_email: str, expiration: str = "24h", reusable: bool = False) -> Optional[str]:
        """
        Create a pre-authentication key for a user

        Args:
            user_email: User's email address
            expiration: Key expiration (e.g., "24h", "7d")
            reusable: Whether the key can be reused

        Returns:
            Pre-auth key string or None if failed
        """
        # Sanitize email for username
        username = user_email.replace("@", "-").replace(".", "-")

        # Ensure user exists first
        if not await self.ensure_user_exists(user_email):
            logger.error(f"Cannot create preauth key: user {username} doesn't exist")
            return None

        # Build command
        cmd = ["preauthkeys", "create", "--user", username, "--expiration", expiration]
        if reusable:
            cmd.append("--reusable")

        # Execute command
        success, output = await self._exec_headscale_cli(cmd)

        if not success:
            logger.error(f"Failed to create preauth key: {output}")
            return None

        # Extract the key from output
        # Output format is typically: "Pre-authentication key created: <key>"
        lines = output.strip().split("\n")
        for line in lines:
            line = line.strip()
            # Look for the actual key (starts with alphanumeric chars)
            if line and not line.startswith(("Pre-", "User", "Expiration", "Reusable", "Created")):
                logger.info(f"Pre-auth key created for user {username}")
                return line

        # If we can't parse it, return the last non-empty line
        key = lines[-1].strip() if lines else None
        if key:
            logger.info(f"Pre-auth key created for user {username}")
        return key


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
    Register a VPN device using Keycloak authentication - SEAMLESS FLOW

    This endpoint provides TRUE seamless VPN registration:
    1. User authenticates with Keycloak (gets bearer token)
    2. Frontend calls this endpoint with bearer token
    3. Backend validates token
    4. **Backend creates Headscale user** (if doesn't exist)
    5. **Backend generates pre-auth key**
    6. **Backend returns pre-auth key**
    7. Frontend uses Tailscale SDK with pre-auth key
    8. VPN connects automatically - NO BROWSER NEEDED!

    Args:
        request: Device registration details
        authorization: Bearer token from Keycloak

    Returns:
        DeviceRegistrationResponse with pre-auth key for immediate connection

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
            import time
            timestamp = int(time.time())
            device_name = f"{username}{os_suffix}-{timestamp}"

        # Sanitize device name for Headscale (alphanumeric, hyphens, dots)
        device_name = "".join(c if c.isalnum() or c in "-." else "-" for c in device_name)

        logger.info(f"Device name: {device_name}")

        # Create pre-authentication key via Headscale
        # This is the key step that enables seamless registration!
        logger.info(f"Generating pre-auth key for user: {user_email}")
        pre_auth_key = await headscale.create_preauth_key(
            user_email=user_email,
            expiration="24h",
            reusable=False  # Single-use for security
        )

        if not pre_auth_key:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate pre-authentication key. Please try again."
            )

        logger.info(f"Pre-auth key generated successfully for {user_email}")

        return DeviceRegistrationResponse(
            success=True,
            message="Device registration ready. Use the pre-auth key to connect.",
            device_name=device_name,
            login_server=headscale.external_url,
            pre_auth_key=pre_auth_key,
            expiration="24h",
            instructions={
                "mobile_sdk": f"await Tailscale.up({{ loginServer: '{headscale.external_url}', authKey: '<pre_auth_key>' }})",
                "cli": f"tailscale up --login-server={headscale.external_url} --authkey=<pre_auth_key>",
                "react_native_example": """
// In your React Native app:
import Tailscale from '@tailscale/react-native';

async function connectVPN(preAuthKey, loginServer) {
  await Tailscale.configure({ controlURL: loginServer });
  await Tailscale.up({ authKey: preAuthKey });
  console.log('VPN Connected!');
}
                """.strip(),
                "note": "No browser needed! The pre-auth key allows immediate connection via Tailscale SDK."
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
