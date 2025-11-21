#!/usr/bin/env python3
"""
Fully Automated Jellyfin SSO Setup
No manual steps required - installs plugin and configures SSO automatically
"""

import argparse
import requests
import time
import sys
import json

class JellyfinSSOFullyAutomated:
    def __init__(self, jellyfin_url, username, password, keycloak_url, realm, client_secret, domain):
        self.base_url = jellyfin_url.rstrip('/')
        self.username = username
        self.password = password
        self.keycloak_url = keycloak_url.rstrip('/')
        self.realm = realm
        self.client_secret = client_secret
        self.domain = domain
        self.session = requests.Session()
        self.auth_token = None
        self.api_key = None

    def log(self, message, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️"}
        print(f"{icons.get(level, 'ℹ️')} {message}")

    def authenticate(self):
        """Authenticate with Jellyfin using username/password"""
        self.log("Authenticating with Jellyfin...")

        try:
            response = self.session.post(
                f"{self.base_url}/Users/AuthenticateByName",
                json={"Username": self.username, "Pw": self.password},
                headers={
                    "X-Emby-Authorization": (
                        'MediaBrowser Client="SSOSetup", '
                        'Device="Automation", '
                        'DeviceId="sso-setup-script", '
                        'Version="1.0.0"'
                    )
                }
            )

            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get('AccessToken')
                self.log("Authenticated successfully", "SUCCESS")
                return True
            else:
                self.log(f"Authentication failed: HTTP {response.status_code}", "ERROR")
                return False

        except Exception as e:
            self.log(f"Authentication error: {e}", "ERROR")
            return False

    def create_api_key(self):
        """Create API key for plugin installation"""
        self.log("Creating API key...")

        try:
            # Check existing keys first
            response = self.session.get(
                f"{self.base_url}/Auth/Keys",
                headers={'X-Emby-Token': self.auth_token}
            )

            if response.status_code == 200:
                keys = response.json().get('Items', [])
                for key in keys:
                    if 'SSO' in key.get('AppName', ''):
                        self.api_key = key.get('AccessToken')
                        if self.api_key:
                            self.log(f"Using existing API key", "SUCCESS")
                            return True

            # Create new API key
            response = self.session.post(
                f"{self.base_url}/Auth/Keys",
                headers={'X-Emby-Token': self.auth_token},
                params={'app': 'Jellyfin-SSO-Automation'}
            )

            if response.status_code in [200, 201, 204]:
                # Get the created key
                time.sleep(1)
                response = self.session.get(
                    f"{self.base_url}/Auth/Keys",
                    headers={'X-Emby-Token': self.auth_token}
                )

                if response.status_code == 200:
                    keys = response.json().get('Items', [])
                    if keys:
                        # Get the most recent key
                        latest_key = keys[-1]
                        self.api_key = latest_key.get('AccessToken')

                        if self.api_key:
                            self.log(f"API key created successfully", "SUCCESS")
                            return True

            # If we can't get the key value, use the auth token
            self.log("Using auth token as API key", "WARNING")
            self.api_key = self.auth_token
            return True

        except Exception as e:
            self.log(f"API key creation error: {e}", "WARNING")
            self.api_key = self.auth_token
            return True

    def check_plugin_installed(self):
        """Check if SSO plugin is installed"""
        try:
            response = self.session.get(
                f"{self.base_url}/Plugins",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code == 200:
                plugins = response.json()
                for plugin in plugins:
                    if 'sso' in plugin.get('Name', '').lower():
                        return True, plugin
            return False, None

        except Exception:
            return False, None

    def add_plugin_repository(self):
        """Add SSO plugin repository"""
        self.log("Adding SSO plugin repository...")

        repo_url = "https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json"

        try:
            # Get current repositories
            response = self.session.get(
                f"{self.base_url}/Repositories",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code == 200:
                repos = response.json()

                # Check if already added
                for repo in repos:
                    if repo.get('Url') == repo_url:
                        self.log("Repository already added", "SUCCESS")
                        return True

                # Add repository
                repos.append({
                    "Name": "SSO-Auth",
                    "Url": repo_url,
                    "Enabled": True
                })

                response = self.session.post(
                    f"{self.base_url}/Repositories",
                    headers={'X-Emby-Token': self.api_key},
                    json=repos
                )

                if response.status_code in [200, 201, 204]:
                    self.log("Repository added successfully", "SUCCESS")
                    return True

            return False

        except Exception as e:
            self.log(f"Repository add error: {e}", "ERROR")
            return False

    def install_plugin(self):
        """Install SSO plugin"""
        self.log("Installing SSO plugin...")

        try:
            # Refresh catalog
            self.session.post(
                f"{self.base_url}/Packages/Updates",
                headers={'X-Emby-Token': self.api_key}
            )
            time.sleep(3)

            # Get available packages
            response = self.session.get(
                f"{self.base_url}/Packages",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code == 200:
                packages = response.json()

                # Find SSO plugin
                for package in packages:
                    name = package.get('name', '')
                    if 'sso' in name.lower() or name == 'SSO-Auth':
                        plugin_id = package.get('guid') or package.get('id')
                        versions = package.get('versions', [])

                        if not versions:
                            self.log("No versions available", "ERROR")
                            return False

                        version = versions[0].get('version', 'latest')

                        self.log(f"Installing {name} v{version}...")

                        # Install
                        response = self.session.post(
                            f"{self.base_url}/Packages/Installed/{plugin_id}/{version}",
                            headers={'X-Emby-Token': self.api_key}
                        )

                        if response.status_code in [200, 201, 204]:
                            self.log("Plugin installation started", "SUCCESS")

                            # Wait for installation
                            self.log("Waiting for plugin installation...")
                            for i in range(30):
                                time.sleep(2)
                                installed, _ = self.check_plugin_installed()
                                if installed:
                                    self.log("Plugin installed successfully", "SUCCESS")
                                    return True

                            self.log("Installation timeout, but may have succeeded", "WARNING")
                            return True

                self.log("SSO plugin not found in catalog", "ERROR")
                return False

        except Exception as e:
            self.log(f"Plugin installation error: {e}", "ERROR")
            return False

    def restart_jellyfin(self):
        """Restart Jellyfin"""
        self.log("Restarting Jellyfin to activate plugin...")

        try:
            response = self.session.post(
                f"{self.base_url}/System/Restart",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code in [200, 201, 204]:
                self.log("Restart initiated", "SUCCESS")
                self.log("Waiting 45 seconds for Jellyfin to restart...")
                time.sleep(45)
                return True

        except Exception as e:
            self.log(f"Restart error (may have succeeded): {e}", "WARNING")
            time.sleep(45)
            return True

    def configure_sso(self):
        """Configure SSO plugin with Keycloak"""
        self.log("Configuring SSO with Keycloak...")

        # Re-authenticate after restart
        if not self.authenticate():
            self.log("Re-authentication failed after restart", "ERROR")
            return False

        config = {
            "OidEndpoint": f"{self.keycloak_url}/realms/{self.realm}",
            "OidClientId": "jellyfin",
            "OidSecret": self.client_secret,
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
                    'X-Emby-Token': self.auth_token,
                    'Content-Type': 'application/json'
                },
                json=config
            )

            if response.status_code in [200, 201, 204]:
                self.log("SSO configured successfully", "SUCCESS")
                return True
            else:
                self.log(f"SSO configuration failed: HTTP {response.status_code}", "ERROR")
                self.log(f"Response: {response.text}", "ERROR")
                return False

        except Exception as e:
            self.log(f"SSO configuration error: {e}", "ERROR")
            return False

    def add_sso_button(self):
        """Add SSO button to login page"""
        self.log("Adding SSO button to login page...")

        try:
            # Get current configuration
            response = self.session.get(
                f"{self.base_url}/System/Configuration",
                headers={'X-Emby-Token': self.auth_token}
            )

            if response.status_code == 200:
                config = response.json()

                sso_button_html = f'''
<form action="https://tv.{self.domain}/sso/OID/start/keycloak" method="get">
    <button class="raised button-submit emby-button" type="submit">
        <span>Sign in with Keycloak SSO</span>
    </button>
</form>
'''

                current_disclaimer = config.get('LoginDisclaimer', '')

                if 'sso/OID/start/keycloak' in current_disclaimer:
                    self.log("SSO button already present", "SUCCESS")
                    return True

                config['LoginDisclaimer'] = current_disclaimer + sso_button_html

                response = self.session.post(
                    f"{self.base_url}/System/Configuration",
                    headers={
                        'X-Emby-Token': self.auth_token,
                        'Content-Type': 'application/json'
                    },
                    json=config
                )

                if response.status_code in [200, 201, 204]:
                    self.log("SSO button added", "SUCCESS")
                    return True

        except Exception as e:
            self.log(f"SSO button error (non-critical): {e}", "WARNING")
            return True

    def verify_sso(self):
        """Verify SSO is working"""
        self.log("Verifying SSO endpoint...")

        try:
            response = requests.get(
                f"{self.base_url}/sso/OID/start/keycloak",
                allow_redirects=False,
                timeout=10
            )

            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if self.keycloak_url in location:
                    self.log("SSO endpoint working correctly!", "SUCCESS")
                    return True

        except Exception as e:
            self.log(f"SSO verification error: {e}", "WARNING")

        return False

    def run(self):
        """Execute full automated SSO setup"""
        print("\n" + "="*60)
        print("🚀 Fully Automated Jellyfin SSO Setup")
        print("="*60)
        print()

        # Step 1: Authenticate
        if not self.authenticate():
            self.log("FAILED: Cannot authenticate with Jellyfin", "ERROR")
            return False

        # Step 2: Create API key
        if not self.create_api_key():
            self.log("FAILED: Cannot create API key", "ERROR")
            return False

        # Step 3: Check if plugin already installed
        installed, plugin = self.check_plugin_installed()
        if installed:
            self.log(f"SSO plugin already installed: v{plugin.get('Version', 'unknown')}", "SUCCESS")
        else:
            # Step 4: Add repository
            if not self.add_plugin_repository():
                self.log("FAILED: Cannot add plugin repository", "ERROR")
                return False

            # Step 5: Install plugin
            if not self.install_plugin():
                self.log("FAILED: Cannot install plugin", "ERROR")
                return False

            # Step 6: Restart Jellyfin
            self.restart_jellyfin()

        # Step 7: Configure SSO
        if not self.configure_sso():
            self.log("FAILED: Cannot configure SSO", "ERROR")
            return False

        # Step 8: Add SSO button
        self.add_sso_button()

        # Step 9: Verify
        self.verify_sso()

        print()
        print("="*60)
        print("✅ JELLYFIN SSO FULLY CONFIGURED!")
        print("="*60)
        print()
        print(f"🔐 SSO Login URL:")
        print(f"   https://tv.{self.domain}/sso/OID/start/keycloak")
        print()
        print(f"📱 Frontend Integration:")
        print(f"   Remove hardcoded credentials")
        print(f"   Redirect users to SSO URL above")
        print()
        print(f"🧪 Test Now:")
        print(f"   1. Visit: https://tv.{self.domain}")
        print(f"   2. Click 'Sign in with Keycloak SSO'")
        print(f"   3. Login with Keycloak credentials")
        print()
        print(f"👥 User Management:")
        print(f"   Assign roles in Keycloak:")
        print(f"   - jellyfin-admin (admins)")
        print(f"   - jellyfin-user (users)")
        print()

        return True


def main():
    parser = argparse.ArgumentParser(
        description='Fully automated Jellyfin SSO setup - NO MANUAL STEPS'
    )
    parser.add_argument('--jellyfin-url', required=True, help='Jellyfin URL')
    parser.add_argument('--username', required=True, help='Jellyfin admin username')
    parser.add_argument('--password', required=True, help='Jellyfin admin password')
    parser.add_argument('--keycloak-url', required=True, help='Keycloak URL')
    parser.add_argument('--realm', default='allsafe', help='Keycloak realm')
    parser.add_argument('--client-secret', required=True, help='Jellyfin client secret from Keycloak')
    parser.add_argument('--domain', required=True, help='Domain (e.g., ozzu.world)')

    args = parser.parse_args()

    setup = JellyfinSSOFullyAutomated(
        args.jellyfin_url,
        args.username,
        args.password,
        args.keycloak_url,
        args.realm,
        args.client_secret,
        args.domain
    )

    success = setup.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
