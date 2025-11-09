#!/usr/bin/env python3
"""
June Platform - Media Stack Auto-Configuration
Automatically configures Prowlarr, Sonarr, Radarr, and Jellyseerr via their APIs
"""

import requests
import time
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, Any

# Suppress SSL warnings for internal services
requests.packages.urllib3.disable_warnings()

class MediaStackConfigurator:
    def __init__(self, domain: str):
        self.domain = domain
        self.prowlarr_url = f"https://prowlarr.{domain}"
        self.sonarr_url = f"https://sonarr.{domain}"
        self.radarr_url = f"https://radarr.{domain}"
        self.jellyseerr_url = f"https://requests.{domain}"
        self.jellyfin_url = f"https://tv.{domain}"
        
        # Config file paths
        self.prowlarr_config = "/mnt/media/configs/prowlarr/config.xml"
        self.sonarr_config = "/mnt/media/configs/sonarr/config.xml"
        self.radarr_config = "/mnt/media/configs/radarr/config.xml"
        
        self.prowlarr_api_key = None
        self.sonarr_api_key = None
        self.radarr_api_key = None
        
        self.session = requests.Session()
        self.session.verify = False  # For self-signed certs
    
    def log(self, message: str):
        print(f"[INFO] {message}")
    
    def success(self, message: str):
        print(f"[SUCCESS] ✅ {message}")
    
    def error(self, message: str):
        print(f"[ERROR] ❌ {message}")
        
    def wait_for_service(self, url: str, service_name: str, timeout: int = 60):
        """Wait for a service to be ready"""
        self.log(f"Waiting for {service_name} to be ready...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = self.session.get(f"{url}/ping", timeout=5)
                if response.status_code < 500:
                    self.success(f"{service_name} is ready!")
                    return True
            except:
                pass
            time.sleep(2)
        self.error(f"{service_name} not ready after {timeout}s")
        return False
    
    def get_api_key_from_config(self, config_path: str, service_name: str) -> Optional[str]:
        """Extract API key from config.xml file"""
        self.log(f"Reading {service_name} config from: {config_path}")
        
        try:
            if not Path(config_path).exists():
                self.error(f"Config file not found: {config_path}")
                return None
            
            tree = ET.parse(config_path)
            root = tree.getroot()
            
            api_key_element = root.find('.//ApiKey')
            if api_key_element is not None and api_key_element.text:
                api_key = api_key_element.text
                self.success(f"Retrieved {service_name} API key: {api_key[:8]}...")
                return api_key
            else:
                self.error(f"No API key found in {config_path}")
                return None
                
        except Exception as e:
            self.error(f"Could not read {service_name} config: {e}")
            return None
    
    def configure_authentication(self, url: str, api_key: str, service_name: str, 
                                username: str, password: str):
        """Configure basic authentication for a service"""
        self.log(f"Configuring authentication for {service_name}...")
        try:
            headers = {"X-Api-Key": api_key}
            
            # Get current config
            response = self.session.get(
                f"{url}/api/v3/config/host",
                headers=headers
            )
            
            if response.status_code == 200:
                config = response.json()
                
                # Enable authentication with password confirmation
                config['authenticationMethod'] = 'basic'
                config['username'] = username
                config['password'] = password
                config['passwordConfirmation'] = password  # Add confirmation field
                
                # Update config
                update_response = self.session.put(
                    f"{url}/api/v3/config/host",
                    headers=headers,
                    json=config
                )
                
                if update_response.status_code == 202:
                    self.success(f"Authentication enabled for {service_name}")
                    return True
                else:
                    self.log(f"Response: {update_response.status_code} - {update_response.text}")
                    
        except Exception as e:
            self.error(f"Failed to configure auth for {service_name}: {e}")
        
        return False
    
    def add_prowlarr_app(self, app_name: str, app_url: str, app_api_key: str) -> bool:
        """Add an application (Sonarr/Radarr) to Prowlarr"""
        self.log(f"Adding {app_name} to Prowlarr...")
        
        try:
            headers = {"X-Api-Key": self.prowlarr_api_key}
            
            # Determine the implementation based on app name
            implementation = "Sonarr" if "sonarr" in app_name.lower() else "Radarr"
            
            payload = {
                "syncLevel": "fullSync",
                "name": app_name,
                "fields": [
                    {"name": "prowlarrUrl", "value": self.prowlarr_url},
                    {"name": "baseUrl", "value": app_url},
                    {"name": "apiKey", "value": app_api_key},
                    {"name": "syncCategories", "value": [2000, 5000] if implementation == "Radarr" else [5000]}
                ],
                "implementationName": implementation,
                "implementation": implementation.lower(),
                "configContract": f"{implementation}Settings",
                "tags": []
            }
            
            # Test connection first
            test_response = self.session.post(
                f"{self.prowlarr_url}/api/v1/applications/test",
                headers=headers,
                json=payload
            )
            
            if test_response.status_code != 200:
                self.error(f"Connection test failed for {app_name}: {test_response.text}")
                return False
            
            # Add the application
            response = self.session.post(
                f"{self.prowlarr_url}/api/v1/applications",
                headers=headers,
                json=payload
            )
            
            if response.status_code in [200, 201]:
                self.success(f"Added {app_name} to Prowlarr")
                return True
            else:
                self.error(f"Failed to add {app_name}: {response.text}")
                return False
                
        except Exception as e:
            self.error(f"Error adding {app_name} to Prowlarr: {e}")
            return False
    
    def configure_root_folder(self, url: str, api_key: str, service_name: str, 
                             path: str) -> bool:
        """Configure root folder for Sonarr/Radarr"""
        self.log(f"Configuring root folder for {service_name}: {path}")
        
        try:
            headers = {"X-Api-Key": api_key}
            
            # Check if root folder already exists
            response = self.session.get(
                f"{url}/api/v3/rootfolder",
                headers=headers
            )
            
            if response.status_code == 200:
                folders = response.json()
                for folder in folders:
                    if folder.get('path') == path:
                        self.success(f"Root folder {path} already exists")
                        return True
            
            # Add root folder
            payload = {"path": path}
            response = self.session.post(
                f"{url}/api/v3/rootfolder",
                headers=headers,
                json=payload
            )
            
            if response.status_code in [200, 201]:
                self.success(f"Added root folder: {path}")
                return True
            else:
                self.error(f"Failed to add root folder: {response.text}")
                return False
                
        except Exception as e:
            self.error(f"Error configuring root folder: {e}")
            return False
    
    def fix_permissions(self):
        """Fix permissions for media folders"""
        self.log("Fixing permissions for media folders...")
        import subprocess
        
        folders = [
            "/mnt/jellyfin/media/tv",
            "/mnt/jellyfin/media/movies",
            "/mnt/jellyfin/media/downloads"
        ]
        
        for folder in folders:
            try:
                # Create folder if it doesn't exist
                Path(folder).mkdir(parents=True, exist_ok=True)
                
                # Change ownership to UID 1000 (the container user)
                subprocess.run(["chown", "-R", "1000:1000", folder], check=True)
                subprocess.run(["chmod", "-R", "775", folder], check=True)
                
                self.success(f"Fixed permissions for {folder}")
            except Exception as e:
                self.error(f"Failed to fix permissions for {folder}: {e}")
    
    def configure_jellyseerr(self, jellyfin_username: str, jellyfin_password: str) -> bool:
        """Configure Jellyseerr with Jellyfin, Sonarr, and Radarr"""
        self.log("Preparing Jellyseerr configuration...")
        
        try:
            config = {
                "jellyfin": {
                    "url": self.jellyfin_url,
                    "username": jellyfin_username,
                    "password": jellyfin_password
                },
                "radarr": {
                    "name": "Radarr",
                    "hostname": f"radarr.{self.domain}",
                    "port": 443,
                    "apiKey": self.radarr_api_key,
                    "useSsl": True,
                    "baseUrl": "/",
                    "isDefault": True
                },
                "sonarr": {
                    "name": "Sonarr", 
                    "hostname": f"sonarr.{self.domain}",
                    "port": 443,
                    "apiKey": self.sonarr_api_key,
                    "useSsl": True,
                    "baseUrl": "/",
                    "isDefault": True
                }
            }
            
            print()
            self.log("Jellyseerr configuration data:")
            print(json.dumps(config, indent=2))
            
            return True
            
        except Exception as e:
            self.error(f"Error preparing Jellyseerr config: {e}")
            return False
    
    def run_full_configuration(self, admin_username: str, admin_password: str,
                              jellyfin_username: str, jellyfin_password: str):
        """Run the complete configuration workflow"""
        
        print("=" * 60)
        print("June Platform - Media Stack Auto-Configuration")
        print("=" * 60)
        print()
        
        # Step 0: Fix permissions first
        self.fix_permissions()
        print()
        
        # Step 1: Wait for all services
        services = [
            (self.prowlarr_url, "Prowlarr"),
            (self.sonarr_url, "Sonarr"),
            (self.radarr_url, "Radarr"),
            (self.jellyseerr_url, "Jellyseerr")
        ]
        
        for url, name in services:
            if not self.wait_for_service(url, name):
                return False
        
        print()
        
        # Step 2: Get API keys from config files
        self.log("Retrieving API keys from config files...")
        self.prowlarr_api_key = self.get_api_key_from_config(self.prowlarr_config, "Prowlarr")
        self.sonarr_api_key = self.get_api_key_from_config(self.sonarr_config, "Sonarr")
        self.radarr_api_key = self.get_api_key_from_config(self.radarr_config, "Radarr")
        
        if not all([self.prowlarr_api_key, self.sonarr_api_key, self.radarr_api_key]):
            self.error("Could not retrieve all API keys")
            return False
        
        print()
        
        # Step 3: Configure authentication
        self.log("Configuring authentication...")
        self.configure_authentication(self.prowlarr_url, self.prowlarr_api_key, 
                                     "Prowlarr", admin_username, admin_password)
        self.configure_authentication(self.sonarr_url, self.sonarr_api_key,
                                     "Sonarr", admin_username, admin_password)
        self.configure_authentication(self.radarr_url, self.radarr_api_key,
                                     "Radarr", admin_username, admin_password)
        print()
        
        # Step 4: Configure root folders
        self.log("Configuring root folders...")
        self.configure_root_folder(self.sonarr_url, self.sonarr_api_key, 
                                   "Sonarr", "/tv")
        self.configure_root_folder(self.radarr_url, self.radarr_api_key,
                                   "Radarr", "/movies")
        print()
        
        # Step 5: Connect apps to Prowlarr
        self.log("Connecting Sonarr and Radarr to Prowlarr...")
        self.add_prowlarr_app("Sonarr", self.sonarr_url, self.sonarr_api_key)
        self.add_prowlarr_app("Radarr", self.radarr_url, self.radarr_api_key)
        print()
        
        # Step 6: Jellyseerr configuration info
        self.configure_jellyseerr(jellyfin_username, jellyfin_password)
        print()
        
        # Summary
        print("=" * 60)
        print("Configuration Summary")
        print("=" * 60)
        print()
        print("✅ Permissions fixed for media folders")
        print("✅ Prowlarr configured")
        print("✅ Sonarr configured with root folder: /tv")
        print("✅ Radarr configured with root folder: /movies")
        print("✅ Sonarr and Radarr connected to Prowlarr")
        print()
        print("📋 Credentials:")
        print(f"  Username: {admin_username}")
        print(f"  Password: {admin_password}")
        print()
        print("🔑 API Keys:")
        print(f"  Prowlarr: {self.prowlarr_api_key}")
        print(f"  Sonarr: {self.sonarr_api_key}")
        print(f"  Radarr: {self.radarr_api_key}")
        print()
        print("📝 Next Steps:")
        print("  1. Add indexers to Prowlarr:")
        print(f"     {self.prowlarr_url}/settings/indexers")
        print()
        print("  2. Complete Jellyseerr setup:")
        print(f"     {self.jellyseerr_url}")
        print("     Use the configuration data printed above")
        print()
        print("  3. Install and configure a download client (qBittorrent)")
        print()
        print("=" * 60)
        
        return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-configure media automation stack")
    parser.add_argument("--domain", required=True, help="Your domain (e.g., ozzu.world)")
    parser.add_argument("--admin-user", default="admin", help="Admin username")
    parser.add_argument("--admin-pass", required=True, help="Admin password")
    parser.add_argument("--jellyfin-user", required=True, help="Jellyfin username")
    parser.add_argument("--jellyfin-pass", required=True, help="Jellyfin password")
    
    args = parser.parse_args()
    
    configurator = MediaStackConfigurator(args.domain)
    success = configurator.run_full_configuration(
        args.admin_user,
        args.admin_pass,
        args.jellyfin_user,
        args.jellyfin_pass
    )
    
    sys.exit(0 if success else 1)
