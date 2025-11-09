#!/usr/bin/env python3
"""
June Platform - Complete Media Stack Auto-Configuration
Runs after installation to configure all connections automatically
"""

import requests
import time
import json
import sys
from pathlib import Path

requests.packages.urllib3.disable_warnings()

class CompleteMediaConfigurator:
    def __init__(self, domain: str):
        self.domain = domain
        self.prowlarr_url = f"https://prowlarr.{domain}"
        self.sonarr_url = f"https://sonarr.{domain}"
        self.radarr_url = f"https://radarr.{domain}"
        
        # Read API keys from saved files
        self.prowlarr_api_key = Path("/root/.prowlarr-api-key").read_text().strip()
        self.sonarr_api_key = Path("/root/.sonarr-api-key").read_text().strip()
        self.radarr_api_key = Path("/root/.radarr-api-key").read_text().strip()
        
        self.session = requests.Session()
        self.session.verify = False
    
    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    
    def add_root_folder(self, url, api_key, service, path):
        """Add root folder to Sonarr/Radarr"""
        self.log(f"Adding root folder {path} to {service}...")
        try:
            headers = {"X-Api-Key": api_key}
            response = self.session.post(
                f"{url}/api/v3/rootfolder",
                headers=headers,
                json={"path": path}
            )
            if response.status_code in [200, 201]:
                self.success(f"Root folder added to {service}")
                return True
        except Exception as e:
            self.error(f"Failed to add root folder: {e}")
        return False
    
    def connect_to_prowlarr(self, app_name, app_url, app_api_key):
        """Connect Sonarr/Radarr to Prowlarr"""
        self.log(f"Connecting {app_name} to Prowlarr...")
        try:
            headers = {"X-Api-Key": self.prowlarr_api_key}
            implementation = "Sonarr" if "sonarr" in app_name.lower() else "Radarr"
            
            payload = {
                "syncLevel": "fullSync",
                "name": app_name,
                "fields": [
                    {"name": "prowlarrUrl", "value": self.prowlarr_url},
                    {"name": "baseUrl", "value": app_url},
                    {"name": "apiKey", "value": app_api_key},
                ],
                "implementationName": implementation,
                "implementation": implementation.lower(),
                "configContract": f"{implementation}Settings",
            }
            
            response = self.session.post(
                f"{self.prowlarr_url}/api/v1/applications",
                headers=headers,
                json=payload
            )
            
            if response.status_code in [200, 201]:
                self.success(f"{app_name} connected to Prowlarr")
                return True
            elif "unique" in response.text.lower():
                self.success(f"{app_name} already connected")
                return True
        except Exception as e:
            self.error(f"Failed to connect {app_name}: {e}")
        return False
    
    def run(self):
        print("=" * 60)
        print("Complete Media Stack Configuration")
        print("=" * 60)
        print()
        
        # Add root folders
        self.add_root_folder(self.sonarr_url, self.sonarr_api_key, "Sonarr", "/tv")
        self.add_root_folder(self.radarr_url, self.radarr_api_key, "Radarr", "/movies")
        print()
        
        # Connect to Prowlarr
        self.connect_to_prowlarr("Sonarr", self.sonarr_url, self.sonarr_api_key)
        self.connect_to_prowlarr("Radarr", self.radarr_url, self.radarr_api_key)
        print()
        
        print("=" * 60)
        print("✅ Configuration Complete!")
        print("=" * 60)
        print()
        print(f"Prowlarr: {self.prowlarr_url}")
        print(f"Sonarr:   {self.sonarr_url}")
        print(f"Radarr:   {self.radarr_url}")
        print()
        print("Next: Add indexers to Prowlarr")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    
    configurator = CompleteMediaConfigurator(args.domain)
    configurator.run()
