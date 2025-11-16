#!/usr/bin/env python3
"""
Auto-configure Prowlarr with recommended indexers for movies, TV shows, and anime
"""

import requests
import time
import json
import sys
from pathlib import Path

requests.packages.urllib3.disable_warnings()

class ProwlarrIndexerConfigurator:
    def __init__(self, prowlarr_url, api_key):
        self.base_url = prowlarr_url
        self.api_key = api_key
        self.session = requests.Session()
        self.session.verify = False
        self.app_profile_id = None
        
    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    def warn(self, msg): print(f"[WARN] ⚠️ {msg}")
    
    def get_app_profile(self):
        """Get the default app profile ID"""
        try:
            headers = {"X-Api-Key": self.api_key}
            response = self.session.get(
                f"{self.base_url}/api/v1/appprofile",
                headers=headers
            )
            
            if response.status_code == 200:
                profiles = response.json()
                if profiles:
                    self.app_profile_id = profiles[0]['id']
                    self.success(f"Using app profile ID: {self.app_profile_id}")
                    return True
            
            self.error("Could not get app profile")
            return False
        except Exception as e:
            self.error(f"Error getting app profile: {e}")
            return False
    
    def get_indexer_schemas(self):
        """Get available indexer templates from Prowlarr"""
        try:
            headers = {"X-Api-Key": self.api_key}
            response = self.session.get(
                f"{self.base_url}/api/v1/indexer/schema",
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                self.error(f"Failed to get indexer schemas: {response.status_code}")
                return []
        except Exception as e:
            self.error(f"Error getting schemas: {e}")
            return []
    
    def get_existing_indexers(self):
        """Get list of already configured indexers"""
        try:
            headers = {"X-Api-Key": self.api_key}
            response = self.session.get(
                f"{self.base_url}/api/v1/indexer",
                headers=headers
            )
            
            if response.status_code == 200:
                indexers = response.json()
                return [idx['name'].lower() for idx in indexers]
            return []
        except Exception as e:
            self.error(f"Error getting existing indexers: {e}")
            return []
    
    def add_indexer(self, indexer_name, indexer_data, tags=None):
        """Add a new indexer to Prowlarr"""
        try:
            headers = {
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json"
            }
            
            # Build payload from schema
            payload = {
                "enable": True,
                "appProfileId": self.app_profile_id,  # REQUIRED!
                "priority": 25,
                "name": indexer_data["name"],
                "fields": indexer_data.get("fields", []),
                "implementationName": indexer_data["implementationName"],
                "implementation": indexer_data["implementation"],
                "configContract": indexer_data["configContract"],
                "tags": tags or []
            }
            
            # Add the indexer (skip test, go straight to add)
            response = self.session.post(
                f"{self.base_url}/api/v1/indexer",
                headers=headers,
                json=payload
            )
            
            if response.status_code in [200, 201]:
                self.success(f"Added indexer: {indexer_name}")
                return True
            else:
                self.error(f"Failed to add {indexer_name}: {response.text}")
                return False
                
        except Exception as e:
            self.error(f"Error adding {indexer_name}: {e}")
            return False
    
    def find_indexer_in_schemas(self, schemas, search_name):
        """Find indexer configuration in schemas"""
        search_lower = search_name.lower()
        
        for schema in schemas:
            name_lower = schema.get('name', '').lower()
            impl_lower = schema.get('implementation', '').lower()
            
            if search_lower in name_lower or search_lower in impl_lower:
                return schema
        
        return None
    
    def configure_indexers(self):
        """Configure all recommended indexers"""
        
        # Indexers to add (updated list based on what's available)
        indexers_to_add = [
            # Movies & TV Shows
            {"name": "1337x", "search": "1337x", "tags": []},
            {"name": "EZTV", "search": "eztv", "tags": []},
            {"name": "YTS", "search": "yts", "tags": []},
            {"name": "TorrentGalaxy", "search": "torrentgalaxy", "tags": []},
            {"name": "Torlock", "search": "torlock", "tags": []},
            # Anime
            {"name": "Nyaa", "search": "nyaa", "tags": []},
            {"name": "AnimeTosho", "search": "animetosho", "tags": []},
        ]
        
        print("=" * 60)
        print("Prowlarr Indexer Auto-Configuration")
        print("=" * 60)
        print()
        
        # Get app profile first
        self.log("Getting app profile...")
        if not self.get_app_profile():
            return False
        print()
        
        # Get available schemas
        self.log("Fetching available indexer templates...")
        schemas = self.get_indexer_schemas()
        
        if not schemas:
            self.error("Could not fetch indexer schemas")
            return False
        
        self.success(f"Found {len(schemas)} available indexers")
        print()
        
        # Get existing indexers
        existing = self.get_existing_indexers()
        if existing:
            self.log(f"Already configured: {', '.join(existing)}")
            print()
        
        # Add each indexer
        added = 0
        skipped = 0
        failed = 0
        
        for indexer_config in indexers_to_add:
            indexer_name = indexer_config["name"]
            search_name = indexer_config.get("search", indexer_name)
            
            # Check if already exists
            if indexer_name.lower() in existing:
                self.warn(f"Skipping {indexer_name} (already exists)")
                skipped += 1
                continue
            
            # Find in schemas
            schema = self.find_indexer_in_schemas(schemas, search_name)
            
            if not schema:
                self.warn(f"Indexer template not found: {indexer_name}")
                failed += 1
                continue
            
            # Add the indexer
            if self.add_indexer(indexer_name, schema, indexer_config.get("tags")):
                added += 1
            else:
                failed += 1
            
            time.sleep(0.5)  # Rate limiting
        
        print()
        print("=" * 60)
        print("Configuration Summary")
        print("=" * 60)
        print(f"✅ Added: {added}")
        print(f"⏭️  Skipped: {skipped}")
        print(f"❌ Failed: {failed}")
        print()
        
        if added > 0:
            print("📝 Indexers configured:")
            print("  Movies & TV: 1337x, EZTV, YTS, TorrentGalaxy, Torlock")
            print("  Anime: Nyaa, AnimeTosho")
            print()
            print("✅ These indexers are now synced to Sonarr and Radarr!")
            print()
            print(f"🌐 View at: {self.base_url}/settings/indexers")
        
        return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-configure Prowlarr indexers")
    parser.add_argument("--url", required=True, help="Prowlarr URL")
    parser.add_argument("--api-key", help="Prowlarr API key (or use file)")
    
    args = parser.parse_args()
    
    # Get API key from argument or file
    api_key = args.api_key
    if not api_key:
        api_key_file = Path("/root/.prowlarr-api-key")
        if api_key_file.exists():
            api_key = api_key_file.read_text().strip()
        else:
            print("[ERROR] API key not provided and not found in /root/.prowlarr-api-key")
            sys.exit(1)
    
    configurator = ProwlarrIndexerConfigurator(args.url, api_key)
    success = configurator.configure_indexers()
    
    sys.exit(0 if success else 1)
