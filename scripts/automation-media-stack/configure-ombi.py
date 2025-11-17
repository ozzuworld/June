#!/usr/bin/env python3
"""
Auto-configure Ombi connections to Jellyfin, Sonarr, Radarr, and Lidarr
"""

import requests
import time
import json
import argparse
from pathlib import Path

requests.packages.urllib3.disable_warnings()

class OmbiConfigurator:
    def __init__(self, domain, username, password):
        self.domain = domain
        self.ombi_url = f"https://ombi.{domain}"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False
        self.api_token = None

        # Read API keys
        try:
            self.sonarr_api_key = Path("/root/.sonarr-api-key").read_text().strip()
            self.radarr_api_key = Path("/root/.radarr-api-key").read_text().strip()
            self.lidarr_api_key = Path("/root/.lidarr-api-key").read_text().strip()
        except Exception as e:
            print(f"[WARN] Could not read all API keys: {e}")
            self.sonarr_api_key = None
            self.radarr_api_key = None
            self.lidarr_api_key = None

    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    def warn(self, msg): print(f"[WARN] ⚠️ {msg}")

    def authenticate(self):
        """Get API token from Ombi"""
        self.log("Authenticating with Ombi...")

        try:
            # Try to read saved token first
            token_file = Path("/root/.ombi-api-token")
            if token_file.exists():
                self.api_token = token_file.read_text().strip()
                if self.api_token:
                    self.log("Using saved API token")
                    return True

            # Otherwise, authenticate
            auth_data = {
                "username": self.username,
                "password": self.password,
                "rememberMe": True
            }

            response = self.session.post(
                f"{self.ombi_url}/api/v1/Token",
                json=auth_data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.api_token = data.get('access_token')
                if self.api_token:
                    self.success("Authentication successful")

                    # Save token for future use
                    try:
                        with open("/root/.ombi-api-token", "w") as f:
                            f.write(self.api_token)
                    except:
                        pass

                    return True

            self.error(f"Authentication failed: {response.status_code}")
            return False

        except Exception as e:
            self.error(f"Authentication error: {e}")
            return False

    def configure_jellyfin(self):
        """Configure Jellyfin connection in Ombi"""
        self.log("Configuring Jellyfin connection...")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            jellyfin_config = {
                "enable": True,
                "servers": [{
                    "name": "Jellyfin",
                    "hostname": f"tv.{self.domain}",
                    "port": 443,
                    "ssl": True,
                    "subDir": "",
                    "administratorId": "admin",
                    "apiKey": "",  # Jellyfin uses user auth, not API key
                    "serverId": "jellyfin-server"
                }],
                "enableEpisodeSearching": True
            }

            response = self.session.post(
                f"{self.ombi_url}/api/v1/Settings/Jellyfin",
                json=jellyfin_config,
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success("Jellyfin configured successfully")
                return True
            else:
                self.warn(f"Jellyfin configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.error(f"Error configuring Jellyfin: {e}")
            return False

    def configure_sonarr(self):
        """Configure Sonarr connection in Ombi"""
        if not self.sonarr_api_key:
            self.warn("Sonarr API key not available, skipping")
            return False

        self.log("Configuring Sonarr connection...")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            sonarr_config = {
                "enable": True,
                "apiKey": self.sonarr_api_key,
                "ip": f"sonarr.{self.domain}",
                "port": 443,
                "ssl": True,
                "subDir": "",
                "qualityProfile": "HD-1080p",  # Will use default if not exists
                "rootPath": "/tv",
                "languageProfile": 1,
                "seasonFolders": True,
                "v3": True,
                "addOnly": False,
                "scanForAvailability": True
            }

            response = self.session.post(
                f"{self.ombi_url}/api/v1/Settings/Sonarr",
                json=sonarr_config,
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success("Sonarr configured successfully")
                return True
            else:
                self.warn(f"Sonarr configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.error(f"Error configuring Sonarr: {e}")
            return False

    def configure_radarr(self):
        """Configure Radarr connection in Ombi"""
        if not self.radarr_api_key:
            self.warn("Radarr API key not available, skipping")
            return False

        self.log("Configuring Radarr connection...")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            radarr_config = {
                "enable": True,
                "apiKey": self.radarr_api_key,
                "ip": f"radarr.{self.domain}",
                "port": 443,
                "ssl": True,
                "subDir": "",
                "qualityProfile": "HD-1080p",  # Will use default if not exists
                "rootPath": "/movies",
                "minimumAvailability": "announced",
                "addOnly": False,
                "scanForAvailability": True
            }

            response = self.session.post(
                f"{self.ombi_url}/api/v1/Settings/Radarr",
                json=radarr_config,
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success("Radarr configured successfully")
                return True
            else:
                self.warn(f"Radarr configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.error(f"Error configuring Radarr: {e}")
            return False

    def configure_lidarr(self):
        """Configure Lidarr connection in Ombi"""
        if not self.lidarr_api_key:
            self.warn("Lidarr API key not available, skipping")
            return False

        self.log("Configuring Lidarr connection...")

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            lidarr_config = {
                "enable": True,
                "apiKey": self.lidarr_api_key,
                "ip": f"lidarr.{self.domain}",
                "port": 443,
                "ssl": True,
                "subDir": "",
                "qualityProfile": "Lossless",  # Will use default if not exists
                "rootPath": "/music",
                "metadataProfileId": 1,
                "languageProfileId": 1,
                "albumFolder": True,
                "addOnly": False
            }

            response = self.session.post(
                f"{self.ombi_url}/api/v1/Settings/Lidarr",
                json=lidarr_config,
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success("Lidarr configured successfully")
                return True
            else:
                self.warn(f"Lidarr configuration returned {response.status_code}: {response.text}")
                return False

        except Exception as e:
            self.error(f"Error configuring Lidarr: {e}")
            return False

    def run(self):
        print("=" * 60)
        print("Ombi Auto-Configuration")
        print("=" * 60)
        print()

        # Authenticate
        if not self.authenticate():
            self.error("Failed to authenticate with Ombi")
            return False

        print()

        # Configure all services
        results = {
            "Jellyfin": self.configure_jellyfin(),
            "Sonarr": self.configure_sonarr(),
            "Radarr": self.configure_radarr(),
            "Lidarr": self.configure_lidarr()
        }

        print()
        print("=" * 60)
        print("Configuration Summary")
        print("=" * 60)
        print()

        for service, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {service}")

        print()
        print(f"Ombi URL: {self.ombi_url}")
        print()
        print("You can now request:")
        print("  - Movies (via Radarr)")
        print("  - TV Shows (via Sonarr)")
        print("  - Music (via Lidarr)")
        print()

        return all(results.values())

def main():
    parser = argparse.ArgumentParser(description='Auto-configure Ombi service connections')
    parser.add_argument('--domain', required=True, help='Domain name')
    parser.add_argument('--username', required=True, help='Ombi admin username')
    parser.add_argument('--password', required=True, help='Ombi admin password')

    args = parser.parse_args()

    configurator = OmbiConfigurator(args.domain, args.username, args.password)

    if configurator.run():
        exit(0)
    else:
        exit(1)

if __name__ == "__main__":
    main()
