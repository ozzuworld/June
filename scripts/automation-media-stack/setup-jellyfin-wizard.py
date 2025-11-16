#!/usr/bin/env python3
"""
Auto-complete Jellyfin initial setup wizard
Creates admin user and completes setup without manual intervention
"""

import requests
import time
import json
import argparse

requests.packages.urllib3.disable_warnings()

class JellyfinSetupAutomator:
    def __init__(self, jellyfin_url, username, password):
        self.base_url = jellyfin_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False

    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")

    def is_setup_required(self):
        """Check if Jellyfin needs initial setup"""
        try:
            response = self.session.get(f"{self.base_url}/Startup/User", timeout=5)
            # If this endpoint returns 200, setup is required
            return response.status_code == 200
        except:
            return False

    def create_admin_user(self):
        """Create the first admin user"""
        self.log(f"Creating admin user: {self.username}")

        try:
            user_data = {
                "Name": self.username,
                "Password": self.password
            }

            response = self.session.post(
                f"{self.base_url}/Startup/User",
                json=user_data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code in [200, 204]:
                self.success(f"Admin user '{self.username}' created successfully")
                return True
            else:
                self.error(f"Failed to create user: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            self.error(f"Error creating user: {e}")
            return False

    def complete_setup(self):
        """Mark setup as complete"""
        self.log("Completing setup wizard...")

        try:
            response = self.session.post(
                f"{self.base_url}/Startup/Complete",
                timeout=10
            )

            if response.status_code in [200, 204]:
                self.success("Setup wizard completed!")
                return True
            else:
                self.error(f"Failed to complete setup: {response.status_code}")
                return False

        except Exception as e:
            self.error(f"Error completing setup: {e}")
            return False

    def configure_remote_access(self):
        """Configure remote access settings"""
        self.log("Configuring remote access...")

        try:
            # This is optional - sets up remote access preferences
            config = {
                "EnableRemoteAccess": True,
                "EnableAutomaticPortMapping": False
            }

            response = self.session.post(
                f"{self.base_url}/Startup/RemoteAccess",
                json=config,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code in [200, 204]:
                self.success("Remote access configured")
                return True
            else:
                # This might not be required, so just log
                self.log("Remote access configuration skipped (not required)")
                return True

        except Exception as e:
            # Non-critical, continue anyway
            self.log(f"Remote access config skipped: {e}")
            return True

    def run_setup(self):
        """Run complete setup automation"""
        print("============================================================")
        print("Jellyfin Initial Setup Automation")
        print("============================================================")
        print("")

        # Check if setup is needed
        if not self.is_setup_required():
            self.log("Jellyfin setup already completed!")
            self.log("Skipping setup wizard automation")
            return True

        self.log("Jellyfin needs initial setup - starting automation...")
        print("")

        # Step 1: Create admin user
        if not self.create_admin_user():
            self.error("Failed to create admin user")
            return False

        time.sleep(1)

        # Step 2: Configure remote access (optional)
        self.configure_remote_access()

        time.sleep(1)

        # Step 3: Complete setup
        if not self.complete_setup():
            self.error("Failed to complete setup wizard")
            return False

        print("")
        self.success("Jellyfin setup wizard completed successfully!")
        print("")
        print(f"Admin credentials:")
        print(f"  Username: {self.username}")
        print(f"  Password: {self.password}")
        print("")
        print(f"Access Jellyfin at: {self.base_url}")
        print("")

        return True

def main():
    parser = argparse.ArgumentParser(description='Auto-complete Jellyfin setup wizard')
    parser.add_argument('--url', required=True, help='Jellyfin URL (e.g., https://tv.domain.com)')
    parser.add_argument('--username', required=True, help='Admin username')
    parser.add_argument('--password', required=True, help='Admin password')

    args = parser.parse_args()

    automator = JellyfinSetupAutomator(args.url, args.username, args.password)

    if automator.run_setup():
        exit(0)
    else:
        exit(1)

if __name__ == "__main__":
    main()
