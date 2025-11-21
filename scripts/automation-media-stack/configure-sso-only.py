#!/usr/bin/env python3
"""
Jellyfin SSO Configuration Only
Assumes SSO plugin is already installed (from custom Docker image)
Only configures the plugin with Keycloak settings
"""

import argparse
import requests
import sys
import time

class JellyfinSSOConfigurator:
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

    def log(self, message, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️"}
        print(f"{icons.get(level, 'ℹ️')} {message}")

    def authenticate(self):
        """Authenticate with Jellyfin"""
        self.log("Authenticating with Jellyfin...")

        try:
            response = self.session.post(
                f"{self.base_url}/Users/AuthenticateByName",
                json={"Username": self.username, "Pw": self.password},
                headers={
                    "X-Emby-Authorization": (
                        'MediaBrowser Client="SSOConfig", '
                        'Device="Automation", '
                        'DeviceId="sso-config-script", '
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

    def check_plugin_installed(self):
        """Check if SSO plugin is installed"""
        self.log("Checking if SSO plugin is installed...")

        try:
            response = self.session.get(
                f"{self.base_url}/Plugins",
                headers={'X-Emby-Token': self.auth_token}
            )

            if response.status_code == 200:
                plugins = response.json()
                for plugin in plugins:
                    if 'sso' in plugin.get('Name', '').lower():
                        self.log(f"SSO plugin found: v{plugin.get('Version', 'unknown')}", "SUCCESS")
                        return True

            self.log("SSO plugin not installed", "ERROR")
            return False

        except Exception as e:
            self.log(f"Plugin check error: {e}", "ERROR")
            return False

    def configure_sso(self):
        """Configure SSO plugin with Keycloak settings"""
        self.log("Configuring SSO with Keycloak...")

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
                self.log(f"Configuration failed: HTTP {response.status_code}", "ERROR")
                self.log(f"Response: {response.text}", "ERROR")
                return False

        except Exception as e:
            self.log(f"Configuration error: {e}", "ERROR")
            return False

    def add_sso_button(self):
        """Add SSO button to login page"""
        self.log("Adding SSO button to login page...")

        try:
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
        """Verify SSO endpoint works"""
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
                    self.log("SSO endpoint working!", "SUCCESS")
                    return True

        except Exception as e:
            self.log(f"Verification error: {e}", "WARNING")

        return False

    def run(self):
        """Execute SSO configuration"""
        print("\n" + "="*60)
        print("🔐 Jellyfin SSO Configuration")
        print("="*60)
        print()

        # Authenticate
        if not self.authenticate():
            self.log("FAILED: Cannot authenticate", "ERROR")
            return False

        # Check plugin is installed
        if not self.check_plugin_installed():
            self.log("FAILED: SSO plugin not installed", "ERROR")
            self.log("The custom Docker image may not have loaded correctly", "ERROR")
            return False

        # Configure SSO
        if not self.configure_sso():
            self.log("FAILED: Cannot configure SSO", "ERROR")
            return False

        # Add SSO button
        self.add_sso_button()

        # Verify
        self.verify_sso()

        print()
        print("="*60)
        print("✅ JELLYFIN SSO CONFIGURED!")
        print("="*60)
        print()
        print(f"🔐 SSO Login URL:")
        print(f"   https://tv.{self.domain}/sso/OID/start/keycloak")
        print()

        return True


def main():
    parser = argparse.ArgumentParser(
        description='Configure Jellyfin SSO (plugin must already be installed)'
    )
    parser.add_argument('--jellyfin-url', required=True, help='Jellyfin URL')
    parser.add_argument('--username', required=True, help='Jellyfin admin username')
    parser.add_argument('--password', required=True, help='Jellyfin admin password')
    parser.add_argument('--keycloak-url', required=True, help='Keycloak URL')
    parser.add_argument('--realm', default='allsafe', help='Keycloak realm')
    parser.add_argument('--client-secret', required=True, help='Jellyfin client secret')
    parser.add_argument('--domain', required=True, help='Domain')

    args = parser.parse_args()

    configurator = JellyfinSSOConfigurator(
        args.jellyfin_url,
        args.username,
        args.password,
        args.keycloak_url,
        args.realm,
        args.client_secret,
        args.domain
    )

    success = configurator.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
