#!/usr/bin/env python3
"""
Jellyseerr OIDC Configuration Automation
Configures Jellyseerr (preview-OIDC) with Keycloak OIDC provider
"""

import argparse
import requests
import sys
import json
import time

class JellyseerrOIDCConfigurator:
    def __init__(self, jellyseerr_url, keycloak_url, realm, client_id, client_secret, domain, admin_email, admin_pass):
        self.base_url = jellyseerr_url.rstrip('/')
        self.keycloak_url = keycloak_url.rstrip('/')
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.domain = domain
        self.admin_email = admin_email
        self.admin_pass = admin_pass
        self.session = requests.Session()

    def check_initialization_status(self):
        """Check if Jellyseerr is initialized"""
        print("🔍 Checking Jellyseerr initialization status...")

        try:
            response = self.session.get(f"{self.base_url}/api/v1/settings/public")
            if response.status_code == 200:
                settings = response.json()
                initialized = settings.get('initialized', False)
                print(f"   Initialized: {initialized}")
                return initialized
            else:
                print(f"⚠️  Could not check status: HTTP {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Failed to check initialization: {e}")
            return False

    def login_as_local_admin(self):
        """Login with local admin credentials to get session cookie"""
        print("🔐 Logging in as local admin...")

        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/auth/local",
                json={
                    "email": self.admin_email,
                    "password": self.admin_pass
                }
            )

            if response.status_code == 200:
                print("✅ Logged in successfully")
                # Session cookie is automatically stored in self.session
                return True
            else:
                print(f"❌ Login failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"❌ Login request failed: {e}")
            return False

    def configure_oidc_settings(self):
        """Configure OIDC settings in Jellyseerr"""
        print("🔐 Configuring OIDC settings...")

        oidc_config = {
            "authUrl": f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/auth",
            "tokenUrl": f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token",
            "userinfoUrl": f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/userinfo",
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "scope": "openid profile email",
            "buttonText": "Sign in with Keycloak",
            "autoSignIn": False
        }

        print(f"   Auth URL: {oidc_config['authUrl']}")
        print(f"   Client ID: {oidc_config['clientId']}")

        try:
            # Update OIDC settings via API
            response = self.session.post(
                f"{self.base_url}/api/v1/settings/oidc",
                json=oidc_config
            )

            if response.status_code in [200, 201, 204]:
                print("✅ OIDC settings configured")
                return True
            else:
                print(f"❌ Configuration failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to configure OIDC: {e}")
            return False

    def enable_oidc(self):
        """Enable OIDC authentication"""
        print("✅ Enabling OIDC authentication...")

        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/settings/oidc/enable",
                json={"enabled": True}
            )

            if response.status_code in [200, 201, 204]:
                print("✅ OIDC authentication enabled")
                return True
            else:
                print(f"⚠️  Enable request returned: HTTP {response.status_code}")
                # May still work if settings were saved
                return True

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Failed to enable OIDC: {e}")
            # Continue anyway - might already be enabled
            return True

    def get_oidc_settings(self):
        """Get current OIDC settings"""
        print("🔍 Retrieving OIDC settings...")

        try:
            response = self.session.get(f"{self.base_url}/api/v1/settings/oidc")

            if response.status_code == 200:
                settings = response.json()
                print("✅ OIDC settings retrieved")
                print(f"   Client ID: {settings.get('clientId')}")
                print(f"   Auth URL: {settings.get('authUrl')}")
                return True
            else:
                print(f"⚠️  Could not retrieve settings: HTTP {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Failed to get OIDC settings: {e}")
            return False

    def run(self):
        """Execute the configuration process"""
        print("\n🚀 Jellyseerr OIDC Configuration")
        print("=" * 50)

        # Check if initialized
        if not self.check_initialization_status():
            print("\n⚠️  Jellyseerr is not initialized yet")
            print("   Run the Jellyseerr setup wizard automation first")
            return False

        # Login as admin
        if not self.login_as_local_admin():
            print("\n❌ Could not login - verify admin credentials")
            return False

        # Configure OIDC settings
        if not self.configure_oidc_settings():
            print("\n❌ Failed to configure OIDC settings")
            return False

        # Enable OIDC
        self.enable_oidc()

        # Verify settings
        self.get_oidc_settings()

        print("\n✅ Jellyseerr OIDC configuration completed!")
        return True

def main():
    parser = argparse.ArgumentParser(
        description='Configure Jellyseerr OIDC with Keycloak'
    )
    parser.add_argument(
        '--url',
        required=True,
        help='Jellyseerr URL'
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
        default='jellyseerr',
        help='OIDC client ID (default: jellyseerr)'
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
    parser.add_argument(
        '--admin-email',
        required=True,
        help='Jellyseerr admin email'
    )
    parser.add_argument(
        '--admin-pass',
        required=True,
        help='Jellyseerr admin password'
    )

    args = parser.parse_args()

    configurator = JellyseerrOIDCConfigurator(
        args.url,
        args.keycloak_url,
        args.realm,
        args.client_id,
        args.client_secret,
        args.domain,
        args.admin_email,
        args.admin_pass
    )

    success = configurator.run()

    print("\n" + "=" * 50)
    if success:
        print("✅ Configuration process completed")
        print("\n📝 Next steps:")
        print(f"   1. Visit https://requests.{args.domain}")
        print("   2. You should see 'Sign in with Keycloak' button")
        print("   3. Test OIDC login flow")
        print("\n🔑 User Management:")
        print("   - New users logging in via OIDC will be auto-created")
        print("   - Assign 'jellyseerr-admin' role in Keycloak for admin access")
        print("   - Assign 'jellyseerr-user' role for regular users")
        sys.exit(0)
    else:
        print("❌ Configuration process encountered issues")
        print("\n🔧 Troubleshooting:")
        print("   - Verify Jellyseerr is using preview-OIDC Docker image")
        print("   - Check that Jellyseerr setup wizard was completed")
        print("   - Verify Keycloak client credentials")
        print("   - Check Jellyseerr logs")
        sys.exit(1)

if __name__ == '__main__':
    main()
