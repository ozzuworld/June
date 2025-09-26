#!/bin/bash
# investigate-auth-flow.sh - Analyze the authentication flow and code logic

set -euo pipefail

echo "🔍 INVESTIGATING AUTHENTICATION FLOW LOGIC"
echo "==========================================="
echo

echo "📋 THE FLOW ANALYSIS"
echo "===================="
echo "Frontend → /v1/chat → Orchestrator (requires auth) → Other services"
echo
echo "The question is: WHAT KIND OF AUTH is expected at each step?"
echo

echo "📋 Step 1: Check What the Chat Endpoint Expects"
echo "==============================================="
echo

echo "Let's examine the chat endpoint authentication requirements:"
echo

# Check the actual route definition
echo "Looking at the orchestrator's chat endpoint code..."
echo

kubectl exec deployment/june-orchestrator -n june-services -- find /app -name "*.py" -exec grep -l "chat\|conversation" {} \; 2>/dev/null || echo "Cannot access orchestrator filesystem"

echo

echo "📋 Step 2: Test What Authentication is Actually Happening"
echo "=========================================================="
echo

echo "Let's test different authentication scenarios:"
echo

echo "🧪 TEST A: No authentication (what frontend is probably doing)"
echo "--------------------------------------------------------------"
curl -X POST "https://api.allsafe.world/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"text":"test message"}' \
  -v 2>&1 | head -20

echo
echo "🧪 TEST B: Check what the endpoint expects"
echo "------------------------------------------"
curl -X GET "https://api.allsafe.world/v1/ping" -v 2>&1 | head -10

echo
echo "🧪 TEST C: Check orchestrator health"
echo "------------------------------------"
curl -X GET "https://api.allsafe.world/healthz" -v 2>&1 | head -10

echo

echo "📋 Step 3: Analyze the Client Credentials Usage"
echo "==============================================="
echo

echo "The Keycloak logs show CLIENT_LOGIN_ERROR for 'june-orchestrator'"
echo "This suggests the orchestrator is trying to use CLIENT CREDENTIALS to call something."
echo "But CLIENT CREDENTIALS are for service-to-service auth, NOT user endpoints."
echo

echo "Let's check what service calls the orchestrator makes:"
echo

echo "Recent orchestrator logs (last 50 lines):"
kubectl logs deployment/june-orchestrator -n june-services --tail=50 | grep -E "(POST|GET|PUT|DELETE|http|auth|token|credential)" || echo "No HTTP requests found in logs"

echo

echo "📋 Step 4: Check Authentication Middleware Configuration"
echo "======================================================="
echo

echo "The orchestrator environment shows these auth configs:"
kubectl exec deployment/june-orchestrator -n june-services -- env | grep -E "(OIDC|KEYCLOAK|AUTH|ISSUER|AUDIENCE)" | sort

echo

echo "📋 Step 5: Understanding the Expected Flow"
echo "=========================================="
echo

echo "CORRECT AUTHENTICATION FLOWS:"
echo
echo "🔄 USER AUTHENTICATION (for chat endpoint):"
echo "   1. User logs in via Keycloak → gets USER TOKEN"
echo "   2. Frontend sends: Authorization: Bearer <USER_TOKEN>"
echo "   3. Orchestrator validates USER TOKEN via JWKS"
echo "   4. Chat endpoint processes request"
echo
echo "🔄 SERVICE AUTHENTICATION (for service-to-service):"
echo "   1. Orchestrator needs to call another service (STT/TTS)"
echo "   2. Orchestrator uses CLIENT CREDENTIALS to get service token"
echo "   3. Orchestrator calls service with service token"
echo

echo "📋 Step 6: Root Cause Analysis"
echo "=============================="
echo

echo "Based on the evidence:"
echo
echo "✅ Keycloak realm exists: allsafe"
echo "✅ Client credentials match"  
echo "✅ External endpoints accessible"
echo "❌ Frontend getting 401 on /v1/chat"
echo "❌ Orchestrator CLIENT_LOGIN_ERROR"
echo

echo "🎯 LIKELY ROOT CAUSES:"
echo
echo "1. 🚨 MISSING USER TOKEN"
echo "   - Frontend not sending Authorization header"
echo "   - Chat endpoint expects USER auth, not client auth"
echo "   - Solution: Frontend needs to authenticate user first"
echo
echo "2. 🚨 BROKEN SERVICE-TO-SERVICE AUTH"  
echo "   - Orchestrator trying to call other services"
echo "   - Client credentials failing for service calls"
echo "   - Solution: Fix client credential configuration"
echo
echo "3. 🚨 MISCONFIGURED AUTH MIDDLEWARE"
echo "   - Auth validation not working properly"
echo "   - Wrong issuer/audience configuration"  
echo "   - Solution: Fix auth configuration"

echo

echo "📋 Step 7: Determine Which Authentication is Failing"
echo "===================================================="
echo

echo "Let's create a test user token to isolate the issue:"
echo

echo "🧪 NEXT INVESTIGATION STEPS:"
echo
echo "A. Create a test user in Keycloak:"
echo "   1. kubectl port-forward -n june-services service/june-idp 8080:8080 &"
echo "   2. http://localhost:8080 → Admin Console"
echo "   3. allsafe realm → Users → Add user"
echo "   4. Set username: testuser, password: test123"
echo "   5. Get user token via:"
echo '      curl -X POST "http://localhost:8080/realms/allsafe/protocol/openid-connect/token" \\'
echo '        -H "Content-Type: application/x-www-form-urlencoded" \\'
echo '        -d "grant_type=password" \\'
echo '        -d "client_id=account" \\'
echo '        -d "username=testuser" \\'
echo '        -d "password=test123"'
echo
echo "B. Test with user token:"
echo '   curl -X POST "https://api.allsafe.world/v1/chat" \\'
echo '     -H "Authorization: Bearer <USER_TOKEN>" \\'
echo '     -H "Content-Type: application/json" \\'
echo '     -d '"'"'{"text":"test message"}'"'"
echo
echo "C. If user token works → Frontend issue"
echo "   If user token fails → Orchestrator auth middleware issue"
echo

echo "📋 IMMEDIATE NEXT STEP"
echo "======================"
echo

echo "Please tell me:"
echo "1. What does your FRONTEND send in the Authorization header?"
echo "2. Does your frontend have a user login flow?"
echo "3. Should the /v1/chat endpoint work without user authentication?"
echo

echo "This will determine if we need to:"
echo "- Fix frontend authentication (add user login)"
echo "- Fix orchestrator auth middleware (make endpoint public)"  
echo "- Fix service-to-service authentication (client credentials)"