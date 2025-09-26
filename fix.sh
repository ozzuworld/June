#!/bin/bash
# setup-keycloak-mobile-client.sh - Configure Keycloak for mobile app

set -euo pipefail

echo "🔧 Setting up Keycloak mobile app client..."

# Port forward to Keycloak
echo "📡 Setting up port forward to Keycloak..."
kubectl port-forward -n june-services service/june-idp 8080:8080 &
PORT_FORWARD_PID=$!

# Wait for port forward
sleep 5

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up..."
    kill $PORT_FORWARD_PID 2>/dev/null || true
}
trap cleanup EXIT

echo "🌐 Keycloak Admin Console: http://localhost:8080"
echo "📋 Realm: allsafe"
echo ""
echo "🔧 Manual Configuration Steps:"
echo ""
echo "1. Go to http://localhost:8080 → Administration Console"
echo "2. Login with admin credentials"
echo "3. Select 'allsafe' realm"
echo ""
echo "4. CREATE MOBILE APP CLIENT:"
echo "   - Clients → Create client"
echo "   - Client ID: june-mobile-app" 
echo "   - Client type: OpenID Connect"
echo "   - Next"
echo ""
echo "5. CONFIGURE CLIENT SETTINGS:"
echo "   - Client authentication: OFF (public client)"
echo "   - Authorization: OFF" 
echo "   - Authentication flow:"
echo "     ☑ Standard flow (Authorization Code Flow)"
echo "     ☑ Direct access grants (Resource Owner Password Flow)"
echo "   - Save"
echo ""
echo "6. SET REDIRECT URIs:"
echo "   - Valid redirect URIs:"
echo "     • june://auth/callback"
echo "     • exp://192.168.0.4:8081"
echo "     • http://localhost:8081"
echo "   - Valid post logout redirect URIs:"
echo "     • june://auth/logout"
echo "   - Web origins: +"
echo "   - Save"
echo ""
echo "7. CREATE TEST USER:"
echo "   - Users → Add user"
echo "   - Username: testuser"
echo "   - Email: test@example.com"
echo "   - Email verified: ON"
echo "   - Save"
echo ""
echo "8. SET USER PASSWORD:"
echo "   - Credentials tab → Set password"
echo "   - Password: test123"
echo "   - Temporary: OFF"
echo "   - Save"
echo ""
echo "9. ASSIGN USER ROLES:"
echo "   - Role mapping tab"
echo "   - Assign role → Filter by clients"
echo "   - Select appropriate roles for june-mobile-app"
echo ""
echo "🔧 After manual setup, run this to test:"

cat << 'EOF'

# Test the configuration
curl -X POST "http://localhost:8080/realms/allsafe/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=june-mobile-app" \
  -d "username=testuser" \
  -d "password=test123"

EOF

echo ""
echo "✅ If this returns a token, your mobile client is configured correctly!"
echo ""
echo "Press Ctrl+C when done configuring..."

# Keep the port forward alive
wait $PORT_FORWARD_PID