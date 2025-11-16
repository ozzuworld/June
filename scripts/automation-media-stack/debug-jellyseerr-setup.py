#!/usr/bin/env python3
"""
Debug script to test Jellyseerr setup completion
Run this from inside the Jellyseerr pod to test the full flow
"""

import requests
import json

requests.packages.urllib3.disable_warnings()

base_url = "http://localhost:5055"
session = requests.Session()
session.verify = False

print("=== Testing Jellyseerr Setup Flow ===\n")

# Step 1: Check current status
resp = session.get(f"{base_url}/api/v1/settings/public")
print(f"1. Current status: initialized={resp.json().get('initialized')}\n")

# Step 2: Authenticate with Jellyfin
print("2. Authenticating with Jellyfin...")
auth_data = {
    "hostname": "jellyfin.june-services.svc.cluster.local",
    "port": 8096,
    "useSsl": False,
    "urlBase": "",
    "username": "hadmin",
    "password": "Pokemon123!",
    "email": "mail@ozzu.world",
    "serverType": 2
}

resp = session.post(f"{base_url}/api/v1/auth/jellyfin", json=auth_data)
print(f"   Status: {resp.status_code}")
if resp.status_code == 200:
    print("   ✅ Authenticated!")
    user_data = resp.json()
    print(f"   User: {user_data.get('user', {}).get('displayName')}")
else:
    print(f"   ❌ Failed: {resp.text}")
    exit(1)

print()

# Step 3: Get session info
resp = session.get(f"{base_url}/api/v1/auth/me")
print(f"3. Session check: {resp.status_code}")
if resp.status_code == 200:
    me = resp.json()
    print(f"   Logged in as: {me.get('displayName')}")
    print(f"   User ID: {me.get('id')}")
print()

# Step 4: Try to set initialized=true
print("4. Attempting to mark as initialized...")
resp = session.post(
    f"{base_url}/api/v1/settings/main",
    json={"initialized": True},
    headers={"Content-Type": "application/json"}
)
print(f"   Status: {resp.status_code}")
print(f"   Response: {resp.text[:200]}")
print()

# Step 5: Check if it worked
resp = session.get(f"{base_url}/api/v1/settings/public")
print(f"5. Final status: initialized={resp.json().get('initialized')}")
