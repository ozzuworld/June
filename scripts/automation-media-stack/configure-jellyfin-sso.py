#!/usr/bin/env python3
"""
Jellyfin SSO Plugin Configuration Automation
Configures the jellyfin-plugin-sso with Keycloak OIDC provider
"""

import argparse
import requests
import sys
import json

class JellyfinSSOConfigurator:
    def __init__(self, jellyfin_url, api_key, keycloak_url, realm, client_id, client_secret, domain):
        self.base_url = jellyfin_url.rstrip('/')
        self.api_key = api_key
        self.keycloak_url = keycloak_url.rstrip('/')
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.domain = domain
        self.session = requests.Session()

    def configure_oidc_provider(self):
        """Configure Keycloak as OIDC provider in Jellyfin SSO plugin"""
        print("🔐 Configuring Keycloak OIDC provider in Jellyfin SSO plugin...")

        provider_name = "keycloak"

        # Build OIDC configuration
        config = {
            "OidEndpoint": f"{self.keycloak_url}/realms/{self.realm}",
            "OidClientId": self.client_id,
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
                f"https://tv.{self.domain}/sso/OID/start/{provider_name}",
                f"https://tv.{self.domain}/sso/OID/redirect/{provider_name}"
            ]
        }

        print(f"   Provider: {provider_name}")
        print(f"   OIDC Endpoint: {config['OidEndpoint']}")
        print(f"   Client ID: {config['OidClientId']}")
        print(f"   Admin Roles: {config['AdminRoles']}")
        print(f"   User Roles: {config['Roles']}")

        try:
            # Configure SSO provider via plugin API
            # The plugin API endpoint requires X-Emby-Token header
            response = self.session.post(
                f"{self.base_url}/sso/OID/Add/{provider_name}",
                headers={
                    'X-Emby-Token': self.api_key,
                    'Content-Type': 'application/json'
                },
                json=config
            )

            if response.status_code in [200, 201, 204]:
                print("✅ Keycloak OIDC provider configured")
                return True
            else:
                print(f"❌ Configuration failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to configure OIDC provider: {e}")
            return False

    def test_oidc_configuration(self):
        """Test OIDC configuration by fetching provider info"""
        print("🧪 Testing OIDC configuration...")

        try:
            # Try to get the provider configuration
            response = self.session.get(
                f"{self.base_url}/sso/OID/Get/keycloak",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code == 200:
                config = response.json()
                print("✅ OIDC provider configuration retrieved")
                print(f"   Enabled: {config.get('Enabled')}")
                return True
            else:
                print(f"⚠️  Could not retrieve configuration: HTTP {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Configuration test failed: {e}")
            return False

    def get_login_disclaimer(self):
        """Get current login disclaimer"""
        try:
            response = self.session.get(
                f"{self.base_url}/System/Configuration",
                headers={'X-Emby-Token': self.api_key}
            )
            if response.status_code == 200:
                config = response.json()
                return config.get('LoginDisclaimer', '')
            return ''
        except:
            return ''

    def add_sso_button_to_login(self):
        """Add SSO login button to Jellyfin login page"""
        print("🎨 Adding SSO button to Jellyfin login page...")

        try:
            # Get current system configuration
            response = self.session.get(
                f"{self.base_url}/System/Configuration",
                headers={'X-Emby-Token': self.api_key}
            )

            if response.status_code != 200:
                print(f"⚠️  Could not get system configuration: HTTP {response.status_code}")
                return False

            config = response.json()

            # Add SSO button HTML to login disclaimer
            sso_button_html = f'''
<form action="https://tv.{self.domain}/sso/OID/start/keycloak" method="get">
    <button class="raised button-submit emby-button" type="submit">
        <span>Sign in with Keycloak SSO</span>
    </button>
</form>
'''

            current_disclaimer = config.get('LoginDisclaimer', '')

            # Check if already added
            if 'sso/OID/start/keycloak' in current_disclaimer:
                print("✅ SSO button already present on login page")
                return True

            # Add SSO button
            config['LoginDisclaimer'] = current_disclaimer + sso_button_html

            # Update configuration
            response = self.session.post(
                f"{self.base_url}/System/Configuration",
                headers={
                    'X-Emby-Token': self.api_key,
                    'Content-Type': 'application/json'
                },
                json=config
            )

            if response.status_code in [200, 201, 204]:
                print("✅ SSO button added to login page")
                return True
            else:
                print(f"⚠️  Failed to update login page: HTTP {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Failed to add SSO button: {e}")
            return False

    def run(self):
        """Execute the configuration process"""
        print("\n🚀 Jellyfin SSO Configuration")
        print("=" * 50)

        # Configure OIDC provider
        if not self.configure_oidc_provider():
            return False

        # Test configuration
        self.test_oidc_configuration()

        # Add SSO button to login page
        self.add_sso_button_to_login()

        print("\n✅ Jellyfin SSO configuration completed!")
        return True

def main():
    parser = argparse.ArgumentParser(
        description='Configure Jellyfin SSO Plugin with Keycloak'
    )
    parser.add_argument(
        '--jellyfin-url',
        required=True,
        help='Jellyfin URL'
    )
    parser.add_argument(
        '--api-key',
        required=True,
        help='Jellyfin API key'
    )
    parser.add_argument(
        '--keycloak-url',
        required=True,
        help='Keycloak URL'
    )
    parser.add_argument(
        '--realm',
        default='allsafe',
        help='Keycloak realm (default: allsafe)'
    )
    parser.add_argument(
        '--client-id',
        default='jellyfin',
        help='OIDC client ID (default: jellyfin)'
    )
    parser.add_argument(
        '--client-secret',
        required=True,
        help='OIDC client secret'
    )
    parser.add_argument(
        '--domain',
        required=True,
        help='Domain (e.g., ozzu.world)'
    )

    args = parser.parse_args()

    configurator = JellyfinSSOConfigurator(
        args.jellyfin_url,
        args.api_key,
        args.keycloak_url,
        args.realm,
        args.client_id,
        args.client_secret,
        args.domain
    )

    success = configurator.run()

    print("\n" + "=" * 50)
    if success:
        print("✅ Configuration process completed")
        print("\n📝 Next steps:")
        print(f"   1. Visit https://tv.{args.domain}")
        print("   2. Click 'Sign in with Keycloak SSO' button")
        print("   3. Test SSO login flow")
        print("\n🔑 User Roles:")
        print("   - Assign 'jellyfin-admin' role for administrators")
        print("   - Assign 'jellyfin-user' role for regular users")
        sys.exit(0)
    else:
        print("❌ Configuration process encountered issues")
        print("\n🔧 Troubleshooting:")
        print("   - Verify SSO plugin is installed and active")
        print("   - Check Jellyfin logs")
        print("   - Verify Keycloak client credentials")
        sys.exit(1)

if __name__ == '__main__':
    main()
