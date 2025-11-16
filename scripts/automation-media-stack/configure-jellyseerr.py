#!/usr/bin/env python3
"""
Jellyseerr Auto-Configuration
Automates the Jellyseerr setup wizard
"""

import requests
import time
import sys

requests.packages.urllib3.disable_warnings()

class JellyseerrConfigurator:
    def __init__(self, domain, jellyfin_user, jellyfin_pass, sonarr_key, radarr_key):
        self.base_url = f"https://requests.{domain}"
        self.jellyfin_url = f"https://tv.{domain}"
        self.sonarr_url = f"https://sonarr.{domain}"
        self.radarr_url = f"https://radarr.{domain}"
        self.jellyfin_user = jellyfin_user
        self.jellyfin_pass = jellyfin_pass
        self.sonarr_key = sonarr_key
        self.radarr_key = radarr_key
        
        self.session = requests.Session()
        self.session.verify = False
    
    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    
    def configure(self):
        print("=" * 60)
        print("Jellyseerr Auto-Configuration")
        print("=" * 60)
        print()
        
        self.log("Note: Jellyseerr requires manual first-time setup")
        self.log("Please complete the wizard with these details:")
        print()
        
        print("Step 3: Configure Media Server")
        print("-" * 40)
        print(f"  Hostname: tv.{self.base_url.split('.')[-2]}.{self.base_url.split('.')[-1]}")
        print("  Port: 443")
        print("  Use SSL: ✓")
        print("  Base URL: /")
        print()
        
        print("Step 4: Configure Services")
        print("-" * 40)
        print("Radarr Configuration:")
        print(f"  Hostname: {self.radarr_url.replace('https://', '')}")
        print("  Port: 443")
        print("  Use SSL: ✓")
        print(f"  API Key: {self.radarr_key}")
        print("  Base URL: /")
        print("  Root Folder: /movies")
        print()
        print("Sonarr Configuration:")
        print(f"  Hostname: {self.sonarr_url.replace('https://', '')}")
        print("  Port: 443")
        print("  Use SSL: ✓")
        print(f"  API Key: {self.sonarr_key}")
        print("  Base URL: /")
        print("  Root Folder: /tv")
        print()
        
        print(f"Access Jellyseerr at: {self.base_url}")

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--jellyfin-user", required=True)
    parser.add_argument("--jellyfin-pass", required=True)
    args = parser.parse_args()
    
    # Read API keys from files
    sonarr_key = Path("/root/.sonarr-api-key").read_text().strip()
    radarr_key = Path("/root/.radarr-api-key").read_text().strip()
    
    configurator = JellyseerrConfigurator(
        args.domain,
        args.jellyfin_user,
        args.jellyfin_pass,
        sonarr_key,
        radarr_key
    )
    configurator.configure()
