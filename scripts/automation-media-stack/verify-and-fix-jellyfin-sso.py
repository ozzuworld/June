#!/usr/bin/env python3
"""
Jellyfin SSO Verification and Auto-Fix Script
Checks SSO configuration and attempts to fix common issues
"""

import argparse
import requests
import sys
import json
import time
from typing import Dict, Optional, Tuple

class JellyfinSSOVerifier:
    def __init__(self, jellyfin_url, username, password, keycloak_url, realm, domain):
        self.base_url = jellyfin_url.rstrip('/')
        self.username = username
        self.password = password
        self.keycloak_url = keycloak_url.rstrip('/')
        self.realm = realm
        self.domain = domain
        self.session = requests.Session()
        self.api_key = None
        self.auth_token = None

    def log(self, message, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️"}
        print(f"{icons.get(level, 'ℹ️')} {message}")

    def authenticate_jellyfin(self) -> bool:
        """Authenticate with Jellyfin using username/password"""
        self.log("Authenticating with Jellyfin...")

        try:
            # Jellyfin authentication endpoint
            auth_data = {
                "Username": self.username,
                "Pw": self.password
            }

            response = self.session.post(
                f"{self.base_url}/Users/AuthenticateByName",
                json=auth_data,
                headers={
                    "X-Emby-Authorization": (
                        'MediaBrowser Client="JellyfinSSO", '
                        'Device="Script", '
                        'DeviceId="verification-script", '
                        'Version="1.0.0"'
                    )
                }
            )

            if response.status_code == 200:
                auth_response = response.json()
                self.auth_token = auth_response.get('AccessToken')

                if self.auth_token:
                    self.log("Successfully authenticated with Jellyfin", "SUCCESS")
                    return True
                else:
                    self.log("Authentication response missing AccessToken", "ERROR")
                    return False
            else:
                self.log(f"Authentication failed: HTTP {response.status_code}", "ERROR")
                self.log(f"Response: {response.text}", "ERROR")
                return False

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to authenticate: {e}", "ERROR")
            return False

    def get_or_create_api_key(self) -> Optional[str]:
        """Get existing or create new API key"""
        self.log("Checking for API keys...")

        if not self.auth_token:
            self.log("Not authenticated, cannot get API key", "ERROR")
            return None

        try:
            # Get existing API keys
            response = self.session.get(
                f"{self.base_url}/Auth/Keys",
                headers={'X-Emby-Token': self.auth_token}
            )

            if response.status_code == 200:
                keys = response.json().get('Items', [])

                # Look for existing SSO key
                for key in keys:
                    if 'SSO' in key.get('AppName', ''):
                        self.log(f"Found existing SSO API key: {key.get('AppName')}", "SUCCESS")
                        # Note: We can't retrieve the actual key value, only see it exists
                        self.log("Using existing API key (value not retrievable)", "WARNING")
                        return "EXISTING_KEY"

                # Create new API key
                self.log("Creating new API key for SSO...")
                response = self.session.post(
                    f"{self.base_url}/Auth/Keys",
                    headers={'X-Emby-Token': self.auth_token},
                    params={'app': 'Jellyfin-SSO-Automation'}
                )

                if response.status_code in [200, 201, 204]:
                    # Try to get the newly created key
                    response = self.session.get(
                        f"{self.base_url}/Auth/Keys",
                        headers={'X-Emby-Token': self.auth_token}
                    )

                    if response.status_code == 200:
                        keys = response.json().get('Items', [])
                        for key in keys:
                            if 'SSO' in key.get('AppName', ''):
                                api_key = key.get('AccessToken')
                                if api_key:
                                    self.log(f"Created new API key: {api_key[:10]}...", "SUCCESS")
                                    return api_key

                    self.log("API key created but value not returned - check Jellyfin dashboard", "WARNING")
                    return "CREATED_CHECK_DASHBOARD"
                else:
                    self.log(f"Failed to create API key: HTTP {response.status_code}", "ERROR")
                    return None
            else:
                self.log(f"Failed to list API keys: HTTP {response.status_code}", "ERROR")
                return None

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to manage API keys: {e}", "ERROR")
            return None

    def check_sso_plugin_installed(self) -> bool:
        """Check if SSO plugin is installed"""
        self.log("Checking if SSO plugin is installed...")

        if not self.auth_token:
            self.log("Not authenticated", "ERROR")
            return False

        try:
            response = self.session.get(
                f"{self.base_url}/Plugins",
                headers={'X-Emby-Token': self.auth_token}
            )

            if response.status_code == 200:
                plugins = response.json()

                for plugin in plugins:
                    if 'sso' in plugin.get('Name', '').lower():
                        version = plugin.get('Version', 'unknown')
                        self.log(f"SSO plugin installed: v{version}", "SUCCESS")
                        return True

                self.log("SSO plugin not found", "WARNING")
                return False
            else:
                self.log(f"Failed to list plugins: HTTP {response.status_code}", "ERROR")
                return False

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to check plugins: {e}", "ERROR")
            return False

    def check_sso_configuration(self, api_key: str) -> Tuple[bool, Optional[Dict]]:
        """Check if SSO is configured"""
        self.log("Checking SSO configuration...")

        try:
            response = self.session.get(
                f"{self.base_url}/sso/OID/Get/keycloak",
                headers={'X-Emby-Token': api_key if api_key else self.auth_token}
            )

            if response.status_code == 200:
                config = response.json()

                if config.get('Enabled'):
                    self.log("SSO is configured and enabled", "SUCCESS")
                    self.log(f"  Endpoint: {config.get('OidEndpoint')}", "INFO")
                    self.log(f"  Client ID: {config.get('OidClientId')}", "INFO")
                    self.log(f"  Admin Roles: {config.get('AdminRoles')}", "INFO")
                    return True, config
                else:
                    self.log("SSO is configured but not enabled", "WARNING")
                    return False, config
            elif response.status_code == 404:
                self.log("SSO provider 'keycloak' not configured", "WARNING")
                return False, None
            else:
                self.log(f"Failed to get SSO config: HTTP {response.status_code}", "ERROR")
                return False, None

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to check SSO configuration: {e}", "ERROR")
            return False, None

    def configure_sso(self, api_key: str, client_secret: str) -> bool:
        """Configure SSO with Keycloak"""
        self.log("Configuring SSO with Keycloak...")

        config = {
            "OidEndpoint": f"{self.keycloak_url}/realms/{self.realm}",
            "OidClientId": "jellyfin",
            "OidSecret": client_secret,
            "Enabled": True,
            "EnableAuthorization": True,
            "EnableAllFolders": True,
            "EnabledFolders": [],
            "AdminRoles": ["jellyfin-admin"],
            "Roles": ["jellyfin-user"],
            "RoleClaim": "realm_access.roles",
            "EnableFolderRoles": False,
            "FolderRoleMapping": [],
            "CanonicalLinks": [
                f"https://tv.{self.domain}/sso/OID/start/keycloak",
                f"https://tv.{self.domain}/sso/OID/redirect/keycloak"
            ]
        }

        try:
            response = self.session.post(
                f"{self.base_url}/sso/OID/Add/keycloak",
                headers={
                    'X-Emby-Token': api_key if api_key else self.auth_token,
                    'Content-Type': 'application/json'
                },
                json=config
            )

            if response.status_code in [200, 201, 204]:
                self.log("SSO configuration successful", "SUCCESS")
                return True
            else:
                self.log(f"SSO configuration failed: HTTP {response.status_code}", "ERROR")
                self.log(f"Response: {response.text}", "ERROR")
                return False

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to configure SSO: {e}", "ERROR")
            return False

    def test_sso_endpoint(self) -> bool:
        """Test if SSO endpoint is accessible"""
        self.log("Testing SSO endpoint...")

        try:
            response = requests.get(
                f"{self.base_url}/sso/OID/start/keycloak",
                allow_redirects=False,
                timeout=5
            )

            # Should redirect to Keycloak
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if self.keycloak_url in location:
                    self.log("SSO endpoint redirects to Keycloak correctly", "SUCCESS")
                    return True
                else:
                    self.log(f"SSO endpoint redirects to unexpected location: {location}", "WARNING")
                    return False
            else:
                self.log(f"SSO endpoint returned unexpected status: HTTP {response.status_code}", "WARNING")
                return False

        except requests.exceptions.RequestException as e:
            self.log(f"Failed to test SSO endpoint: {e}", "ERROR")
            return False

    def run_verification(self, client_secret: Optional[str] = None, fix: bool = False) -> bool:
        """Run full verification and optionally fix issues"""
        self.log("=" * 60)
        self.log("Jellyfin SSO Verification")
        self.log("=" * 60)

        # Step 1: Authenticate
        if not self.authenticate_jellyfin():
            self.log("\n❌ FAILED: Cannot authenticate with Jellyfin", "ERROR")
            self.log("  Check username and password in config.env", "ERROR")
            return False

        # Step 2: Check plugin
        plugin_installed = self.check_sso_plugin_installed()
        if not plugin_installed:
            self.log("\n❌ FAILED: SSO plugin not installed", "ERROR")
            self.log("  Install manually via: Dashboard > Plugins > Repositories", "ERROR")
            self.log("  Add repository: https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json", "ERROR")
            return False

        # Step 3: Get/create API key
        api_key = self.get_or_create_api_key()
        if not api_key or api_key in ["EXISTING_KEY", "CREATED_CHECK_DASHBOARD"]:
            self.log("\n⚠️  Cannot auto-configure without API key", "WARNING")
            self.log("  Get API key from: Dashboard > API Keys", "WARNING")
            self.log("  Then run: python3 configure-jellyfin-sso.py --api-key YOUR_KEY", "WARNING")

            if not fix:
                return False

        # Step 4: Check SSO configuration
        is_configured, config = self.check_sso_configuration(api_key)

        if not is_configured and fix and client_secret and api_key:
            self.log("\n🔧 Attempting to fix SSO configuration...")
            if self.configure_sso(api_key, client_secret):
                is_configured = True
            else:
                self.log("\n❌ FAILED: Could not configure SSO", "ERROR")
                return False

        if not is_configured:
            self.log("\n❌ FAILED: SSO not properly configured", "ERROR")
            return False

        # Step 5: Test SSO endpoint
        sso_works = self.test_sso_endpoint()

        self.log("\n" + "=" * 60)
        if plugin_installed and is_configured and sso_works:
            self.log("✅ Jellyfin SSO is properly configured and working!", "SUCCESS")
            self.log("\n🔑 SSO Login URL:")
            self.log(f"  https://tv.{self.domain}/sso/OID/start/keycloak")
            self.log("\n📱 Frontend Integration:")
            self.log(f"  Instead of hardcoding credentials, redirect users to SSO URL")
            self.log(f"  After Keycloak auth, users will be redirected back to Jellyfin")
            self.log("=" * 60)
            return True
        else:
            self.log("❌ Jellyfin SSO verification failed", "ERROR")
            self.log("=" * 60)
            return False


def main():
    parser = argparse.ArgumentParser(
        description='Verify and fix Jellyfin SSO configuration'
    )
    parser.add_argument('--jellyfin-url', required=True, help='Jellyfin URL')
    parser.add_argument('--username', required=True, help='Jellyfin admin username')
    parser.add_argument('--password', required=True, help='Jellyfin admin password')
    parser.add_argument('--keycloak-url', required=True, help='Keycloak URL')
    parser.add_argument('--realm', default='allsafe', help='Keycloak realm')
    parser.add_argument('--domain', required=True, help='Domain (e.g., ozzu.world)')
    parser.add_argument('--client-secret', help='Jellyfin client secret from Keycloak')
    parser.add_argument('--fix', action='store_true', help='Attempt to fix issues automatically')

    args = parser.parse_args()

    verifier = JellyfinSSOVerifier(
        args.jellyfin_url,
        args.username,
        args.password,
        args.keycloak_url,
        args.realm,
        args.domain
    )

    success = verifier.run_verification(args.client_secret, args.fix)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
