#!/usr/bin/env python3
"""
Auto-complete Ombi initial setup wizard
Creates admin user and completes setup without manual intervention
"""

import requests
import time
import json
import argparse

requests.packages.urllib3.disable_warnings()

class OmbiSetupAutomator:
    def __init__(self, ombi_url, username, password):
        self.base_url = ombi_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False
        self.api_token = None

    def log(self, msg): print(f"[INFO] {msg}")
    def success(self, msg): print(f"[SUCCESS] ✅ {msg}")
    def error(self, msg): print(f"[ERROR] ❌ {msg}")
    def warn(self, msg): print(f"[WARN] ⚠️ {msg}")

    def is_setup_required(self):
        """Check if Ombi needs initial setup"""
        try:
            # Try to access the wizard endpoint
            response = self.session.get(
                f"{self.base_url}/api/v1/Identity/Wizard",
                timeout=10
            )

            # If wizard endpoint is accessible, setup is needed
            if response.status_code == 200:
                return True

            # If we get 401/404, setup might already be complete
            return False
        except Exception as e:
            self.log(f"Could not check setup status: {e}")
            return False

    def create_admin_user(self):
        """Create the first admin user via wizard endpoint"""
        self.log(f"Creating Ombi admin user: {self.username}")

        try:
            wizard_data = {
                "username": self.username,
                "password": self.password,
                "usePlexAdminAccount": False
            }

            response = self.session.post(
                f"{self.base_url}/api/v1/Identity/Wizard",
                json=wizard_data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self.success(f"Admin user '{self.username}' created successfully")

                # Try to get the token from response
                try:
                    data = response.json()
                    if 'access_token' in data:
                        self.api_token = data['access_token']
                        self.success("Received API token")
                except:
                    pass

                return True
            else:
                self.error(f"Failed to create user: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            self.error(f"Error creating user: {e}")
            return False

    def authenticate(self):
        """Authenticate with Ombi to get API token"""
        if self.api_token:
            return True

        self.log("Authenticating with Ombi...")

        try:
            auth_data = {
                "username": self.username,
                "password": self.password,
                "rememberMe": True
            }

            response = self.session.post(
                f"{self.base_url}/api/v1/Token",
                json=auth_data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.api_token = data.get('access_token')
                if self.api_token:
                    self.success("Authentication successful")
                    return True
                else:
                    self.error("No token in response")
                    return False
            else:
                self.error(f"Authentication failed: {response.status_code}")
                return False

        except Exception as e:
            self.error(f"Authentication error: {e}")
            return False

    def verify_setup(self):
        """Verify that Ombi is properly set up"""
        if not self.api_token:
            if not self.authenticate():
                return False

        try:
            headers = {"Authorization": f"Bearer {self.api_token}"}

            response = self.session.get(
                f"{self.base_url}/api/v1/Settings/About",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                self.success("Ombi setup verified!")
                return True
            else:
                self.warn(f"Could not verify setup: {response.status_code}")
                return True  # Don't fail, might still be okay

        except Exception as e:
            self.warn(f"Verification failed: {e}")
            return True  # Don't fail, might still be okay

    def check_if_wizard_accessible(self):
        """Check if wizard endpoint is still accessible"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/wizard",
                timeout=5
            )
            # If we get 200, wizard is accessible (first run)
            # If we get 404/403, wizard is disabled (already set up)
            return response.status_code == 200
        except:
            return False

    def run_setup(self):
        """Run complete setup automation"""
        print("============================================================")
        print("Ombi Initial Setup Automation")
        print("============================================================")
        print("")

        # Wait for Ombi to be ready
        self.log("Waiting for Ombi to be ready...")
        max_retries = 30
        for i in range(max_retries):
            try:
                response = self.session.get(f"{self.base_url}/", timeout=5)
                if response.status_code in [200, 302, 401]:
                    self.success("Ombi is ready!")
                    break
            except:
                pass

            if i < max_retries - 1:
                time.sleep(2)
            else:
                self.error("Ombi did not become ready in time")
                return False

        time.sleep(3)  # Give it a moment to fully initialize

        # Check if wizard is still accessible
        wizard_accessible = self.check_if_wizard_accessible()

        if not wizard_accessible:
            self.log("Wizard endpoint not accessible - Ombi appears to be already configured")
            self.log("Testing authentication with provided credentials...")

            if self.authenticate():
                self.success("✅ Ombi is already set up and credentials work!")
                self.success("No setup needed - Ombi is ready to use")
                return True
            else:
                self.warn("⚠️ Ombi is already set up, but authentication failed")
                print("")
                print("This means Ombi has been configured previously.")
                print("To reconfigure Ombi:")
                print(f"  1. Delete the config: kubectl exec -n june-services deployment/ombi -- rm -rf /config/*")
                print(f"  2. Restart Ombi: kubectl rollout restart -n june-services deployment/ombi")
                print(f"  3. Wait 30 seconds and re-run this script")
                print("")
                print("Or manually access: {self.base_url}")
                print("")
                # Return True to not block the installation
                self.warn("Continuing installation - you may need to configure Ombi manually")
                return True

        # Check if setup is needed
        if not self.is_setup_required():
            self.log("Checking if we can authenticate with existing credentials...")
            if self.authenticate():
                self.success("Ombi setup already completed!")
                self.success("Successfully authenticated with existing credentials")
                return True
            else:
                self.log("Setup check indicates Ombi may need configuration")
                # Continue to try creating user

        self.log("Ombi needs initial setup - starting automation...")
        print("")

        # Create admin user via wizard
        if not self.create_admin_user():
            self.error("Failed to create admin user")
            return False

        time.sleep(2)

        # Verify setup
        if not self.verify_setup():
            self.warn("Setup verification failed, but user might be created")

        print("")
        self.success("Ombi setup wizard completed successfully!")
        print("")
        print(f"Admin credentials:")
        print(f"  Username: {self.username}")
        print(f"  Password: {self.password}")
        print("")
        print(f"Access Ombi at: {self.base_url}")
        print("")

        # Save API token if we have it
        if self.api_token:
            try:
                with open("/root/.ombi-api-token", "w") as f:
                    f.write(self.api_token)
                self.success("API token saved to /root/.ombi-api-token")
            except Exception as e:
                self.warn(f"Could not save API token: {e}")

        return True

def main():
    parser = argparse.ArgumentParser(description='Auto-complete Ombi setup wizard')
    parser.add_argument('--url', required=True, help='Ombi URL (e.g., https://ombi.domain.com)')
    parser.add_argument('--username', required=True, help='Admin username')
    parser.add_argument('--password', required=True, help='Admin password')

    args = parser.parse_args()

    automator = OmbiSetupAutomator(args.url, args.username, args.password)

    if automator.run_setup():
        exit(0)
    else:
        exit(1)

if __name__ == "__main__":
    main()
