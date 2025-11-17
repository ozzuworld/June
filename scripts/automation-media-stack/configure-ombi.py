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

            # Jellyfin uses EmbySettings model (inherits from ExternalSettings)
            jellyfin_config = {
                "enable": True,
                "servers": [{
                    "serverId": "jellyfin-main",
                    "name": "Jellyfin",
                    "apiKey": "",  # Jellyfin requires separate auth setup
                    "administratorId": "",
                    "enableEpisodeSearching": True,
                    "embySelectedLibraries": [],
                    # ExternalSettings base properties
                    "ip": f"tv.{self.domain}",  # Hostname/IP only
                    "port": 443,
                    "ssl": True,
                    "subDir": ""
                }]
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

    def get_sonarr_profiles_and_folders(self):
        """Get quality profiles and root folders from Sonarr"""
        try:
            sonarr_url = f"https://sonarr.{self.domain}"
            headers = {"X-Api-Key": self.sonarr_api_key}

            # Get quality profiles
            profiles_response = self.session.get(
                f"{sonarr_url}/api/v3/qualityprofile",
                headers=headers,
                timeout=10
            )
            quality_profile_id = None
            if profiles_response.status_code == 200:
                profiles = profiles_response.json()
                if profiles:
                    quality_profile_id = profiles[0]['id']  # Use first profile
                    self.log(f"Found Sonarr quality profile: {profiles[0]['name']} (ID: {quality_profile_id})")

            # Get root folders
            folders_response = self.session.get(
                f"{sonarr_url}/api/v3/rootfolder",
                headers=headers,
                timeout=10
            )
            root_path = "/tv"
            if folders_response.status_code == 200:
                folders = folders_response.json()
                if folders:
                    root_path = folders[0]['path']
                    self.log(f"Found Sonarr root folder: {root_path}")

            # Get language profiles
            lang_response = self.session.get(
                f"{sonarr_url}/api/v3/languageprofile",
                headers=headers,
                timeout=10
            )
            language_profile_id = 1
            if lang_response.status_code == 200:
                lang_profiles = lang_response.json()
                if lang_profiles:
                    language_profile_id = lang_profiles[0]['id']

            return quality_profile_id, root_path, language_profile_id
        except Exception as e:
            self.warn(f"Could not load Sonarr profiles: {e}")
            return None, "/tv", 1

    def configure_sonarr(self):
        """Configure Sonarr connection in Ombi"""
        if not self.sonarr_api_key:
            self.warn("Sonarr API key not available, skipping")
            return False

        self.log("Configuring Sonarr connection...")
        self.log("Loading quality profiles and root folders from Sonarr...")
        quality_profile_id, root_path, language_profile_id = self.get_sonarr_profiles_and_folders()

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            # SonarrSettings model (from ExternalSettings)
            sonarr_config = {
                "enabled": True,  # Not "enable"
                "apiKey": self.sonarr_api_key,
                "qualityProfile": str(quality_profile_id) if quality_profile_id else "Any",  # String
                "rootPath": root_path,  # String (path or ID)
                "languageProfile": language_profile_id,  # Int
                "seasonFolders": True,
                "addOnly": False,
                "scanForAvailability": True,
                "prioritizeArrAvailability": False,
                "sendUserTags": False,
                "tag": None,
                # ExternalSettings base properties
                "ssl": True,
                "subDir": "",
                "ip": f"sonarr.{self.domain}",
                "port": 443
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

    def get_radarr_profiles_and_folders(self):
        """Get quality profiles and root folders from Radarr"""
        try:
            radarr_url = f"https://radarr.{self.domain}"
            headers = {"X-Api-Key": self.radarr_api_key}

            # Get quality profiles
            profiles_response = self.session.get(
                f"{radarr_url}/api/v3/qualityprofile",
                headers=headers,
                timeout=10
            )
            quality_profile_id = None
            if profiles_response.status_code == 200:
                profiles = profiles_response.json()
                if profiles:
                    quality_profile_id = profiles[0]['id']  # Use first profile
                    self.log(f"Found Radarr quality profile: {profiles[0]['name']} (ID: {quality_profile_id})")

            # Get root folders
            folders_response = self.session.get(
                f"{radarr_url}/api/v3/rootfolder",
                headers=headers,
                timeout=10
            )
            root_path_id = None
            if folders_response.status_code == 200:
                folders = folders_response.json()
                if folders:
                    root_path_id = str(folders[0]['id'])  # Use ID as string
                    root_path = folders[0]['path']
                    self.log(f"Found Radarr root folder: {root_path} (ID: {root_path_id})")

            return quality_profile_id, root_path_id if root_path_id else "/movies"
        except Exception as e:
            self.warn(f"Could not load Radarr profiles: {e}")
            return None, "/movies"

    def configure_radarr(self):
        """Configure Radarr connection in Ombi"""
        if not self.radarr_api_key:
            self.warn("Radarr API key not available, skipping")
            return False

        self.log("Configuring Radarr connection...")
        self.log("Loading quality profiles and root folders from Radarr...")
        quality_profile_id, root_path_id = self.get_radarr_profiles_and_folders()

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            # RadarrSettings model (from ExternalSettings)
            radarr_config = {
                "enabled": True,  # Not "enable"
                "apiKey": self.radarr_api_key,
                "defaultQualityProfile": str(quality_profile_id) if quality_profile_id else "Any",
                "defaultRootPath": root_path_id,  # Root folder ID, not path
                "minimumAvailability": "announced",
                "addOnly": False,
                "scanForAvailability": True,
                "prioritizeArrAvailability": False,
                "sendUserTags": False,
                "tag": None,
                # ExternalSettings base properties
                "ssl": True,
                "subDir": "",
                "ip": f"radarr.{self.domain}",
                "port": 443
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

    def get_lidarr_profiles_and_folders(self):
        """Get quality profiles and root folders from Lidarr"""
        try:
            lidarr_url = f"https://lidarr.{self.domain}"
            headers = {"X-Api-Key": self.lidarr_api_key}

            # Get quality profiles
            profiles_response = self.session.get(
                f"{lidarr_url}/api/v1/qualityprofile",
                headers=headers,
                timeout=10
            )
            quality_profile_id = None
            if profiles_response.status_code == 200:
                profiles = profiles_response.json()
                if profiles:
                    quality_profile_id = profiles[0]['id']  # Use first profile
                    self.log(f"Found Lidarr quality profile: {profiles[0]['name']} (ID: {quality_profile_id})")

            # Get root folders
            folders_response = self.session.get(
                f"{lidarr_url}/api/v1/rootfolder",
                headers=headers,
                timeout=10
            )
            root_path = "/music"
            if folders_response.status_code == 200:
                folders = folders_response.json()
                if folders:
                    root_path = folders[0]['path']
                    self.log(f"Found Lidarr root folder: {root_path}")

            # Get metadata profiles
            metadata_response = self.session.get(
                f"{lidarr_url}/api/v1/metadataprofile",
                headers=headers,
                timeout=10
            )
            metadata_profile_id = 1
            if metadata_response.status_code == 200:
                metadata_profiles = metadata_response.json()
                if metadata_profiles:
                    metadata_profile_id = metadata_profiles[0]['id']

            return quality_profile_id, root_path, metadata_profile_id
        except Exception as e:
            self.warn(f"Could not load Lidarr profiles: {e}")
            return None, "/music", 1

    def configure_lidarr(self):
        """Configure Lidarr connection in Ombi"""
        if not self.lidarr_api_key:
            self.warn("Lidarr API key not available, skipping")
            return False

        self.log("Configuring Lidarr connection...")
        self.log("Loading quality profiles and root folders from Lidarr...")
        quality_profile_id, root_path, metadata_profile_id = self.get_lidarr_profiles_and_folders()

        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }

            # LidarrSettings model (from ExternalSettings)
            lidarr_config = {
                "enabled": True,  # Not "enable"
                "apiKey": self.lidarr_api_key,
                "defaultQualityProfile": str(quality_profile_id) if quality_profile_id else "Any",  # String, not "qualityProfile"
                "defaultRootPath": root_path,  # Not "rootPath"
                "metadataProfileId": metadata_profile_id,  # Int
                "albumFolder": True,
                "addOnly": False,
                # ExternalSettings base properties
                "ssl": True,
                "subDir": "",
                "ip": f"lidarr.{self.domain}",
                "port": 443
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
            print()
            print("Ombi configuration requires successful setup first.")
            print("Please ensure:")
            print("  1. Ombi setup wizard completed successfully")
            print("  2. Credentials match what was configured")
            print()
            print("To reset Ombi:")
            print("  kubectl exec -n june-services deployment/ombi -- rm -rf /config/*")
            print("  kubectl rollout restart -n june-services deployment/ombi")
            print()
            self.warn("Skipping Ombi configuration - you can configure manually at:")
            print(f"  {self.ombi_url}")
            print()
            # Return True to not block installation
            return True

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
