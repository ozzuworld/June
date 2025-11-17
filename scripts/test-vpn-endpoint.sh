#!/bin/bash
# Test VPN registration endpoint and show the actual response

echo "🧪 Testing VPN Device Registration Endpoint"
echo ""

# Check if token is provided
if [ -z "$1" ]; then
    echo "❌ Error: No bearer token provided"
    echo ""
    echo "Usage: $0 <bearer_token>"
    echo ""
    echo "To get a token, authenticate with Keycloak first:"
    echo "  curl -X POST https://idp.ozzu.world/realms/allsafe/protocol/openid-connect/token \\"
    echo "    -H 'Content-Type: application/x-www-form-urlencoded' \\"
    echo "    -d 'grant_type=password' \\"
    echo "    -d 'client_id=<client-id>' \\"
    echo "    -d 'username=test@test.com' \\"
    echo "    -d 'password=<password>' | jq -r '.access_token'"
    exit 1
fi

TOKEN="$1"

echo "📡 Sending request to VPN registration endpoint..."
echo ""

# Get orchestrator pod for internal testing
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

if [ -n "$POD" ]; then
    echo "Testing from inside pod: $POD"
    echo ""

    kubectl exec -n june-services $POD -- curl -s -X POST http://localhost:8080/api/v1/device/register \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "device_os": "android",
        "device_model": "Test Device"
      }' | python3 -m json.tool

    echo ""
else
    echo "❌ No orchestrator pod found!"
    exit 1
fi

echo ""
echo "📋 Expected response structure:"
echo "{"
echo '  "success": true,'
echo '  "message": "Device registration ready. Use the pre-auth key to connect.",'
echo '  "device_name": "test-android-<timestamp>",'
echo '  "login_server": "https://headscale.ozzu.world",'
echo '  "pre_auth_key": "<actual-key-here>", // 👈 THIS IS WHAT THE FRONTEND NEEDS'
echo '  "expiration": "24h",'
echo '  "instructions": { ... }'
echo "}"
