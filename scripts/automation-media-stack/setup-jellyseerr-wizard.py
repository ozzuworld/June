#!/usr/bin/env python3
"""
Auto-complete Jellyseerr initial setup wizard
Connects to Jellyfin, Sonarr, and Radarr automatically
"""

import requests
import time
import json
import argparse
import os

requests.packages.urllib3.disable_warnings()

class JellyseerrSetupAutomator:
    def __init__(self, jellyseerr_url, domain, jellyfin_user, jellyfin_pass, jellyfin_internal_url=None):
        self.base_url = jellyseerr_url.rstrip('/')
        self.domain = domain
        self.jellyfin_user = jellyfin_user
        self.jellyfin_pass = jellyfin_pass
        # Use internal Kubernetes service URL for Jellyfin if not specified
        self.jellyfin_url = jellyfin_internal_url or "http://jellyfin.june-services.svc.cluster.local:8096"
        self.session = requests.Session()
        self.session.verify = False
        self.api_token = None

    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    def warn(self, msg): print(f"[WARN] ⚠️ {msg}")

    def is_initialized(self):
        """Check if Jellyseerr has been initialized"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/settings/public",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                # If initialized is False, setup is needed
                return data.get('initialized', False)
            return False
        except Exception as e:
            self.log(f"Could not check initialization status: {e}")
            return False

    def initialize_application(self):
        """Initialize Jellyseerr application"""
        self.log("Initializing Jellyseerr application...")

        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/settings/initialize",
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success("Jellyseerr initialized successfully")
                return True
            else:
                self.warn(f"Initialize returned status {response.status_code}, continuing anyway...")
                return True

        except Exception as e:
            self.warn(f"Initialize request failed: {e}, continuing anyway...")
            return True

    def test_jellyfin_connectivity(self, jellyfin_url):
        """Test if Jellyfin server is reachable"""
        try:
            # Try to reach the Jellyfin system info endpoint (doesn't require auth)
            test_session = requests.Session()
            test_session.verify = False
            response = test_session.get(
                f"{jellyfin_url}/System/Info/Public",
                timeout=5
            )
            if response.status_code == 200:
                return True, "Server reachable"
            else:
                return False, f"Server returned {response.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Connection refused: {e}"
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except Exception as e:
            return False, f"Error: {e}"

    def authenticate_with_jellyfin(self):
        """Authenticate Jellyseerr with Jellyfin server and create admin user"""

        # If a custom URL was provided, use it
        if self.jellyfin_url != "http://jellyfin.june-services.svc.cluster.local:8096":
            urls_to_try = [self.jellyfin_url]
        else:
            # Try multiple common service name patterns for deployed Jellyfin
            urls_to_try = [
                "http://jellyfin.june-services.svc.cluster.local:8096",           # Standard service name
                f"https://tv.{self.domain}"                                        # External URL fallback
            ]

        last_error = None
        for jellyfin_url in urls_to_try:
            self.log(f"Trying Jellyfin server at {jellyfin_url}...")

            # First test if we can reach Jellyfin
            reachable, msg = self.test_jellyfin_connectivity(jellyfin_url)
            if not reachable:
                self.warn(f"Jellyfin not reachable: {msg}")
                last_error = msg
                continue
            else:
                self.log(f"Jellyfin reachable: {msg}")

            try:
                # Parse the URL into components Jellyseerr expects
                from urllib.parse import urlparse
                parsed = urlparse(jellyfin_url)

                # Jellyseerr expects separate hostname, port, useSsl fields
                auth_data = {
                    "authToken": "",  # Empty for username/password auth
                    "hostname": parsed.hostname,
                    "port": parsed.port or (8920 if parsed.scheme == 'https' else 8096),
                    "useSsl": parsed.scheme == 'https',
                    "urlBase": parsed.path.rstrip('/') if parsed.path and parsed.path != '/' else "",
                    "username": self.jellyfin_user,
                    "password": self.jellyfin_pass,
                    "email": f"{self.jellyfin_user}@{self.domain}",
                    "serverType": 1  # MediaServerType.JELLYFIN = 1 (PLEX=0, JELLYFIN=1, EMBY=2)
                }

                self.log(f"Sending auth with hostname={auth_data['hostname']}, port={auth_data['port']}, useSsl={auth_data['useSsl']}")

                response = self.session.post(
                    f"{self.base_url}/api/v1/auth/jellyfin",
                    json=auth_data,
                    headers={"Content-Type": "application/json"},
                    timeout=15
                )

                if response.status_code == 200:
                    data = response.json()
                    self.success(f"Authenticated with Jellyfin as admin user: {self.jellyfin_user}")
                    self.success(f"Connected using URL: {jellyfin_url}")
                    self.jellyfin_url = jellyfin_url  # Save the working URL
                    return True
                else:
                    last_error = f"{response.status_code} - {response.text}"
                    self.warn(f"Failed with {jellyfin_url}: {last_error}")
                    continue

            except Exception as e:
                last_error = str(e)
                self.warn(f"Failed with {jellyfin_url}: {e}")
                continue

        # All URLs failed
        self.error(f"Could not authenticate with any Jellyfin URL")
        self.error(f"Last error: {last_error}")
        return False

    def read_api_key(self, service):
        """Read API key from file"""
        # Try multiple locations (host vs pod)
        key_files = [
            f"/tmp/{service}-api-key",      # Inside pod
            f"/root/.{service}-api-key"     # On host
        ]

        for key_file in key_files:
            try:
                with open(key_file, 'r') as f:
                    api_key = f.read().strip()
                    if api_key:
                        return api_key
            except FileNotFoundError:
                continue
            except Exception as e:
                self.warn(f"Error reading {key_file}: {e}")
                continue

        self.warn(f"API key file not found for {service}")
        return None

    def configure_radarr(self):
        """Add Radarr service to Jellyseerr"""
        self.log("Configuring Radarr connection...")

        radarr_api_key = self.read_api_key("radarr")
        if not radarr_api_key:
            self.warn("Radarr API key not found, skipping Radarr configuration")
            return False

        try:
            radarr_config = {
                "name": "Radarr",
                "hostname": "radarr.june-services.svc.cluster.local",
                "port": 7878,
                "apiKey": radarr_api_key,
                "useSsl": False,
                "baseUrl": "",
                "activeProfileId": 1,
                "activeProfileName": "Any",
                "activeDirectory": "/movies",
                "is4k": False,
                "minimumAvailability": "released",
                "tags": [],
                "isDefault": True,
                "externalUrl": f"https://radarr.{self.domain}",
                "syncEnabled": True
            }

            response = self.session.post(
                f"{self.base_url}/api/v1/settings/radarr",
                json=radarr_config,
                headers={"Content-Type": "application/json"},
                timeout=15
            )

            if response.status_code in [200, 201]:
                self.success("Radarr configured successfully")
                return True
            else:
                self.warn(f"Radarr configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.warn(f"Error configuring Radarr: {e}")
            return False

    def configure_sonarr(self):
        """Add Sonarr service to Jellyseerr"""
        self.log("Configuring Sonarr connection...")

        sonarr_api_key = self.read_api_key("sonarr")
        if not sonarr_api_key:
            self.warn("Sonarr API key not found, skipping Sonarr configuration")
            return False

        try:
            sonarr_config = {
                "name": "Sonarr",
                "hostname": "sonarr.june-services.svc.cluster.local",
                "port": 8989,
                "apiKey": sonarr_api_key,
                "useSsl": False,
                "baseUrl": "",
                "activeProfileId": 1,
                "activeProfileName": "Any",
                "activeDirectory": "/tv",
                "activeAnimeProfileId": None,
                "activeAnimeProfileName": None,
                "activeAnimeDirectory": None,
                "tags": [],
                "animeTags": [],
                "is4k": False,
                "isDefault": True,
                "externalUrl": f"https://sonarr.{self.domain}",
                "syncEnabled": True,
                "enableSeasonFolders": True
            }

            response = self.session.post(
                f"{self.base_url}/api/v1/settings/sonarr",
                json=sonarr_config,
                headers={"Content-Type": "application/json"},
                timeout=15
            )

            if response.status_code in [200, 201]:
                self.success("Sonarr configured successfully")
                return True
            else:
                self.warn(f"Sonarr configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.warn(f"Error configuring Sonarr: {e}")
            return False

    def run_setup(self):
        """Run complete Jellyseerr setup automation"""
        print("============================================================")
        print("Jellyseerr Initial Setup Automation")
        print("============================================================")
        print("")

        # Check if already initialized
        if self.is_initialized():
            self.log("Jellyseerr is already initialized!")
            self.log("Skipping setup wizard automation")
            print("")
            print(f"Access Jellyseerr at: {self.base_url}")
            return True

        self.log("Jellyseerr needs initial setup - starting automation...")
        print("")

        # Step 1: Initialize application
        if not self.initialize_application():
            self.error("Failed to initialize Jellyseerr")
            return False

        time.sleep(2)

        # Step 2: Authenticate with Jellyfin (creates admin user)
        if not self.authenticate_with_jellyfin():
            self.error("Failed to authenticate with Jellyfin")
            self.log("")
            self.log("Manual setup required:")
            self.log(f"  1. Navigate to {self.base_url}/setup")
            self.log(f"  2. Sign in with Jellyfin credentials")
            self.log(f"  3. Configure Sonarr and Radarr")
            return False

        time.sleep(2)

        # Step 3: Configure Radarr
        radarr_success = self.configure_radarr()

        time.sleep(1)

        # Step 4: Configure Sonarr
        sonarr_success = self.configure_sonarr()

        print("")
        self.success("Jellyseerr setup wizard completed!")
        print("")
        print(f"🎭 Jellyseerr Access:")
        print(f"  URL: {self.base_url}")
        print(f"  Login: Use your Jellyfin credentials ({self.jellyfin_user})")
        print("")

        if radarr_success and sonarr_success:
            print(f"✅ Services Connected:")
            print(f"  - Jellyfin: {self.jellyfin_url} (internal) / https://tv.{self.domain} (external)")
            print(f"  - Radarr: https://radarr.{self.domain}")
            print(f"  - Sonarr: https://sonarr.{self.domain}")
        else:
            print(f"⚠️  Some services may need manual configuration:")
            if not radarr_success:
                print(f"  - Radarr: https://radarr.{self.domain}")
            if not sonarr_success:
                print(f"  - Sonarr: https://sonarr.{self.domain}")

        print("")
        print(f"🎬 Ready to use! Request content via Jellyseerr.")
        print("")

        return True

def main():
    parser = argparse.ArgumentParser(description='Auto-complete Jellyseerr setup wizard')
    parser.add_argument('--url', required=True, help='Jellyseerr URL (e.g., https://requests.domain.com)')
    parser.add_argument('--domain', required=True, help='Base domain (e.g., example.com)')
    parser.add_argument('--jellyfin-user', required=True, help='Jellyfin admin username')
    parser.add_argument('--jellyfin-pass', required=True, help='Jellyfin admin password')
    parser.add_argument('--jellyfin-url', required=False,
                       help='Jellyfin internal URL (default: http://jellyfin.june-services.svc.cluster.local:8096)')

    args = parser.parse_args()

    automator = JellyseerrSetupAutomator(
        args.url,
        args.domain,
        args.jellyfin_user,
        args.jellyfin_pass,
        args.jellyfin_url
    )

    if automator.run_setup():
        exit(0)
    else:
        exit(1)

if __name__ == "__main__":
    main()
