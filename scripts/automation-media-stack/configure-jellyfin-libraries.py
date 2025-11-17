#!/usr/bin/env python3
"""
Auto-configure Jellyfin libraries via API
"""

import requests
import time
import json

requests.packages.urllib3.disable_warnings()

class JellyfinLibraryConfigurator:
    def __init__(self, jellyfin_url, username, password):
        self.base_url = jellyfin_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False
        self.api_key = None
        self.user_id = None
        
    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    
    def check_initial_setup(self):
        """Check if Jellyfin needs initial setup"""
        try:
            response = self.session.get(f"{self.base_url}/Startup/User", timeout=5)
            # If this endpoint is accessible, Jellyfin needs initial setup
            if response.status_code == 200:
                return True
            return False
        except:
            return False

    def authenticate(self):
        """Authenticate and get API token"""
        self.log("Authenticating with Jellyfin...")

        # Check if Jellyfin needs initial setup
        if self.check_initial_setup():
            self.error("Jellyfin requires initial setup")
            self.error("Please visit the Jellyfin web UI and complete the setup wizard")
            self.error("Then re-run this script to configure libraries")
            return False

        try:
            # Login to get access token
            auth_data = {
                "Username": self.username,
                "Pw": self.password
            }

            headers = {
                "Content-Type": "application/json",
                "X-Emby-Authorization": 'MediaBrowser Client="Jellyfin CLI", Device="Script", DeviceId="script-001", Version="1.0.0"'
            }

            response = self.session.post(
                f"{self.base_url}/Users/AuthenticateByName",
                json=auth_data,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.api_key = data['AccessToken']
                self.user_id = data['User']['Id']
                self.success("Authenticated successfully!")
                return True
            elif response.status_code == 401:
                self.error("Invalid username or password")
                self.error("Make sure you completed Jellyfin setup with these credentials")
                return False
            else:
                self.error(f"Authentication failed: {response.text}")
                return False

        except requests.exceptions.Timeout:
            self.error("Connection timeout - Jellyfin may not be ready yet")
            return False
        except Exception as e:
            self.error(f"Authentication error: {e}")
            return False
    
    def create_library(self, name, content_type, path):
        """Create a media library"""
        self.log(f"Creating {content_type} library: {name}")
        
        try:
            headers = {
                "X-MediaBrowser-Token": self.api_key
            }
            
            # Map content types to Jellyfin collection types
            collection_types = {
                "movies": "movies",
                "tvshows": "tvshows",
                "music": "music"
            }
            
            params = {
                "name": name,
                "collectionType": collection_types.get(content_type, content_type),
                "paths": path,
                "refreshLibrary": "false"
            }
            
            response = self.session.post(
                f"{self.base_url}/Library/VirtualFolders",
                headers=headers,
                params=params
            )
            
            if response.status_code in [200, 204]:
                self.success(f"Created library: {name}")
                return True
            else:
                self.error(f"Failed to create library: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.error(f"Error creating library: {e}")
            return False
    
    def check_library_exists(self, name):
        """Check if library already exists"""
        try:
            headers = {"X-MediaBrowser-Token": self.api_key}
            
            response = self.session.get(
                f"{self.base_url}/Library/VirtualFolders",
                headers=headers
            )
            
            if response.status_code == 200:
                libraries = response.json()
                for lib in libraries:
                    if lib['Name'] == name:
                        return True
            return False
            
        except Exception as e:
            self.error(f"Error checking libraries: {e}")
            return False
    
    def run(self):
        print("=" * 60)
        print("Jellyfin Library Auto-Configuration")
        print("=" * 60)
        print()
        
        # Authenticate
        if not self.authenticate():
            return False
        
        print()
        
        # Define libraries to create
        libraries = [
            {
                "name": "Movies",
                "type": "movies",
                "path": "/movies"
            },
            {
                "name": "TV Shows",
                "type": "tvshows",
                "path": "/tv"
            },
            {
                "name": "Music",
                "type": "music",
                "path": "/music"
            }
        ]
        
        # Create libraries
        for lib in libraries:
            if self.check_library_exists(lib['name']):
                self.log(f"Library '{lib['name']}' already exists, skipping...")
            else:
                self.create_library(lib['name'], lib['type'], lib['path'])
        
        print()
        print("=" * 60)
        print("✅ Jellyfin libraries configured!")
        print("=" * 60)
        print()
        print("Libraries created:")
        print("  - Movies (/movies)")
        print("  - TV Shows (/tv)")
        print("  - Music (/music)")
        print()
        print("Next: Go back to Jellyseerr and click 'Sync Libraries'")
        
        return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-configure Jellyfin libraries")
    parser.add_argument("--url", required=True, help="Jellyfin URL (e.g., https://tv.ozzu.world)")
    parser.add_argument("--username", required=True, help="Jellyfin admin username")
    parser.add_argument("--password", required=True, help="Jellyfin admin password")
    
    args = parser.parse_args()
    
    configurator = JellyfinLibraryConfigurator(args.url, args.username, args.password)
    success = configurator.run()
    
    exit(0 if success else 1)
