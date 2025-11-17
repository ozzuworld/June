#!/usr/bin/env python3
"""
Jellyfin SSO Plugin Installation Automation
Installs and enables the jellyfin-plugin-sso via Jellyfin API
"""

import argparse
import requests
import time
import sys
from urllib.parse import urlparse

class JellyfinSSOInstaller:
    def __init__(self, jellyfin_url, api_key):
        self.base_url = jellyfin_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-Emby-Token': api_key,
            'Content-Type': 'application/json'
        })

    def add_plugin_repository(self):
        """Add the SSO plugin repository to Jellyfin"""
        print("📦 Adding SSO plugin repository...")

        repo_url = "https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json"

        # Get current repositories
        try:
            response = self.session.get(f"{self.base_url}/Repositories")
            response.raise_for_status()
            repos = response.json()

            # Check if already added
            for repo in repos:
                if repo.get('Url') == repo_url:
                    print("✅ SSO plugin repository already added")
                    return True

            # Add repository
            repos.append({
                "Name": "SSO-Auth",
                "Url": repo_url,
                "Enabled": True
            })

            response = self.session.post(
                f"{self.base_url}/Repositories",
                json=repos
            )
            response.raise_for_status()
            print("✅ SSO plugin repository added")
            return True

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to add repository: {e}")
            return False

    def refresh_plugin_catalog(self):
        """Refresh the plugin catalog"""
        print("🔄 Refreshing plugin catalog...")
        try:
            response = self.session.post(
                f"{self.base_url}/Packages/Updates"
            )
            # This endpoint might return various status codes
            time.sleep(2)  # Wait for refresh
            print("✅ Plugin catalog refreshed")
            return True
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Catalog refresh warning: {e}")
            # Continue anyway
            return True

    def install_sso_plugin(self):
        """Install the SSO plugin"""
        print("💾 Installing SSO plugin...")

        try:
            # Get available packages
            response = self.session.get(f"{self.base_url}/Packages")
            response.raise_for_status()
            packages = response.json()

            # Find SSO plugin
            sso_plugin = None
            for package in packages:
                if package.get('name') == 'SSO-Auth' or 'sso' in package.get('name', '').lower():
                    sso_plugin = package
                    break

            if not sso_plugin:
                print("❌ SSO plugin not found in catalog")
                return False

            plugin_id = sso_plugin.get('guid') or sso_plugin.get('id')
            version = sso_plugin.get('versions', [{}])[0].get('version', 'latest')

            print(f"   Plugin ID: {plugin_id}")
            print(f"   Version: {version}")

            # Install plugin
            response = self.session.post(
                f"{self.base_url}/Packages/Installed/{plugin_id}/{version}"
            )

            if response.status_code in [200, 201, 204]:
                print("✅ SSO plugin installation started")
                return True
            else:
                print(f"❌ Installation failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to install plugin: {e}")
            return False

    def check_plugin_status(self):
        """Check if SSO plugin is installed"""
        print("🔍 Checking plugin status...")
        try:
            response = self.session.get(f"{self.base_url}/Plugins")
            response.raise_for_status()
            plugins = response.json()

            for plugin in plugins:
                if 'sso' in plugin.get('Name', '').lower():
                    print(f"✅ SSO plugin found: {plugin.get('Name')} v{plugin.get('Version')}")
                    return True, plugin

            print("⚠️  SSO plugin not installed yet")
            return False, None

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to check plugin status: {e}")
            return False, None

    def wait_for_installation(self, timeout=120):
        """Wait for plugin installation to complete"""
        print(f"⏳ Waiting for installation to complete (timeout: {timeout}s)...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            installed, plugin = self.check_plugin_status()
            if installed:
                return True
            time.sleep(5)
            print("   Still waiting...")

        print("⚠️  Installation timeout - may need manual verification")
        return False

    def restart_jellyfin(self):
        """Restart Jellyfin to activate plugin"""
        print("🔄 Restarting Jellyfin to activate plugin...")
        try:
            response = self.session.post(f"{self.base_url}/System/Restart")
            if response.status_code in [200, 201, 204]:
                print("✅ Restart command sent")
                print("⏳ Waiting 30 seconds for Jellyfin to restart...")
                time.sleep(30)
                return True
            else:
                print(f"⚠️  Restart may have failed: HTTP {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Restart request failed: {e}")
            return False

    def run(self):
        """Execute the installation process"""
        print("\n🚀 Jellyfin SSO Plugin Installation")
        print("=" * 50)

        # Check if already installed
        installed, plugin = self.check_plugin_status()
        if installed:
            print("\n✅ SSO plugin is already installed!")
            print(f"   Version: {plugin.get('Version')}")
            return True

        # Add repository
        if not self.add_plugin_repository():
            return False

        # Refresh catalog
        self.refresh_plugin_catalog()

        # Install plugin
        if not self.install_sso_plugin():
            return False

        # Wait for installation
        if self.wait_for_installation():
            print("\n✅ SSO plugin installation completed!")

            # Ask about restart
            print("\n⚠️  Jellyfin needs to restart to activate the plugin")
            print("   You can restart manually or let this script do it")
            restart = input("Restart Jellyfin now? [y/N]: ").strip().lower()

            if restart == 'y':
                self.restart_jellyfin()
            else:
                print("\n📝 Manual restart required:")
                print("   kubectl rollout restart deployment/jellyfin -n media-stack")

            return True
        else:
            print("\n⚠️  Installation may still be in progress")
            print("   Check Jellyfin dashboard > Plugins after a few minutes")
            return False

def main():
    parser = argparse.ArgumentParser(
        description='Install Jellyfin SSO Plugin via API'
    )
    parser.add_argument(
        '--url',
        required=True,
        help='Jellyfin URL (e.g., http://jellyfin.media-stack.svc.cluster.local:8096)'
    )
    parser.add_argument(
        '--api-key',
        required=True,
        help='Jellyfin API key'
    )

    args = parser.parse_args()

    installer = JellyfinSSOInstaller(args.url, args.api_key)

    success = installer.run()

    print("\n" + "=" * 50)
    if success:
        print("✅ Installation process completed")
        print("\n📝 Next steps:")
        print("   1. Verify plugin in Jellyfin dashboard > Plugins")
        print("   2. Configure SSO provider (Keycloak) in plugin settings")
        print("   3. Test SSO login")
        sys.exit(0)
    else:
        print("❌ Installation process encountered issues")
        print("\n🔧 Troubleshooting:")
        print("   - Check Jellyfin logs")
        print("   - Verify API key is correct")
        print("   - Try manual installation from Jellyfin dashboard")
        sys.exit(1)

if __name__ == '__main__':
    main()
