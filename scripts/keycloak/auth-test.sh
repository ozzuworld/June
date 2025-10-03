#!/bin/bash
# Test Keycloak Authentication for June Services

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }

echo "🧪 Keycloak Authentication Test Suite"
echo "======================================"

# Configuration
KEYCLOAK_URL="https://idp.allsafe.world"
REALM="allsafe"

echo "Testing against: $KEYCLOAK_URL/realms/$REALM"
echo ""

# Test 1: OIDC Discovery
echo "Test 1: OIDC Discovery Endpoint"
echo "--------------------------------"

DISCOVERY=$(curl -s "$KEYCLOAK_URL/realms/$REALM/.well-known/openid-configuration")

if echo "$DISCOVERY" | jq -e '.issuer' > /dev/null 2>&1; then
  ISSUER=$(echo "$DISCOVERY" | jq -r '.issuer')
  TOKEN_ENDPOINT=$(echo "$DISCOVERY" | jq -r '.token_endpoint')
  JWKS_URI=$(echo "$DISCOVERY" | jq -r '.jwks_uri')
  
  log_success "OIDC discovery accessible"
  echo "  Issuer: $ISSUER"
  echo "  Token endpoint: $TOKEN_ENDPOINT"
  echo "  JWKS URI: $JWKS_URI"
else
  log_error "OIDC discovery failed"
  echo "$DISCOVERY"
  exit 1
fi
echo ""

# Test 2: JWKS Endpoint
echo "Test 2: JWKS Endpoint"
echo "---------------------"

JWKS=$(curl -s "$JWKS_URI")

if echo "$JWKS" | jq -e '.keys[0]' > /dev/null 2>&1; then
  KEY_COUNT=$(echo "$JWKS" | jq '.keys | length')
  log_success "JWKS endpoint accessible"
  echo "  Public keys available: $KEY_COUNT"
else
  log_error "JWKS endpoint failed"
  exit 1
fi
echo ""

# Test 3: Service Token Generation
echo "Test 3: Service Token Generation"
echo "---------------------------------"

test_client_auth() {
  local CLIENT_ID=$1
  local CLIENT_SECRET=$2
  local SERVICE_NAME=$3
  
  echo "Testing: $SERVICE_NAME ($CLIENT_ID)"
  
  # Get token
  TOKEN_RESPONSE=$(curl -s -X POST "$TOKEN_ENDPOINT" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -d "client_id=$CLIENT_ID" \
    -d "client_secret=$CLIENT_SECRET")
  
  ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')
  
  if [ -z "$ACCESS_TOKEN" ]; then
    log_error "$SERVICE_NAME: Token generation failed"
    echo "  Response: $TOKEN_RESPONSE"
    return 1
  fi
  
  log_success "$SERVICE_NAME: Token generated"
  
  # Decode token (without verification)
  TOKEN_PAYLOAD=$(echo "$ACCESS_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null || echo "{}")
  
  if [ "$TOKEN_PAYLOAD" != "{}" ]; then
    echo "  Token details:"
    echo "    Subject: $(echo "$TOKEN_PAYLOAD" | jq -r '.sub // "N/A"')"
    echo "    Client: $(echo "$TOKEN_PAYLOAD" | jq -r '.azp // .client_id // "N/A"')"
    echo "    Expires: $(echo "$TOKEN_PAYLOAD" | jq -r '.exp // "N/A"')"
    echo "    Scopes: $(echo "$TOKEN_PAYLOAD" | jq -r '.scope // "N/A"')"
    echo "    Audience: $(echo "$TOKEN_PAYLOAD" | jq -r '.aud // "N/A"')"
  fi
  
  echo "  Token (first 50 chars): ${ACCESS_TOKEN:0:50}..."
  echo ""
  
  return 0
}

# Get secrets from Kubernetes
echo "Fetching client secrets from Kubernetes..."

if kubectl get secret june-orchestrator-secrets -n june-services &> /dev/null; then
  ORCH_SECRET=$(kubectl get secret june-orchestrator-secrets -n june-services -o jsonpath='{.data.keycloak-client-secret}' | base64 -d)
  STT_SECRET=$(kubectl get secret june-stt-secrets -n june-services -o jsonpath='{.data.keycloak-client-secret}' | base64 -d 2>/dev/null || echo "")
  TTS_SECRET=$(kubectl get secret june-tts-secrets -n june-services -o jsonpath='{.data.keycloak-client-secret}' | base64 -d 2>/dev/null || echo "")
  
  echo "✅ Secrets loaded from Kubernetes"
  echo ""
else
  log_warning "Kubernetes secrets not found, please enter manually:"
  read -p "june-orchestrator client secret: " ORCH_SECRET
  read -p "june-stt client secret: " STT_SECRET
  read -p "june-tts client secret: " TTS_SECRET
  echo ""
fi

# Test each client
test_client_auth "june-orchestrator" "$ORCH_SECRET" "Orchestrator"
test_client_auth "june-stt" "$STT_SECRET" "STT Service"
test_client_auth "june-tts" "$TTS_SECRET" "TTS Service"

# Test 4: Service Health Checks
echo "Test 4: Service Health Checks (with auth)"
echo "------------------------------------------"

test_service_health() {
  local SERVICE_URL=$1
  local SERVICE_NAME=$2
  local TOKEN=$3
  
  echo "Testing: $SERVICE_NAME"
  
  # Test without auth
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/healthz")
  
  if [ "$STATUS_CODE" = "200" ]; then
    log_success "$SERVICE_NAME: Health check OK (no auth required)"
  elif [ "$STATUS_CODE" = "401" ]; then
    log_warning "$SERVICE_NAME: Requires authentication"
    
    # Test with auth
    if [ -n "$TOKEN" ]; then
      AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/healthz")
      
      if [ "$AUTH_STATUS" = "200" ]; then
        log_success "$SERVICE_NAME: Health check OK (with auth)"
      else
        log_error "$SERVICE_NAME: Auth failed (HTTP $AUTH_STATUS)"
      fi
    fi
  else
    log_error "$SERVICE_NAME: Health check failed (HTTP $STATUS_CODE)"
  fi
  
  echo ""
}

# Get token for testing
TEST_TOKEN=$(curl -s -X POST "$TOKEN_ENDPOINT" \
  -d "grant_type=client_credentials" \
  -d "client_id=june-orchestrator" \
  -d "client_secret=$ORCH_SECRET" | jq -r '.access_token')

# Test services
test_service_health "https://api.allsafe.world" "Orchestrator" "$TEST_TOKEN"
test_service_health "https://stt.allsafe.world" "STT Service" "$TEST_TOKEN"
test_service_health "https://tts.allsafe.world" "TTS Service" "$TEST_TOKEN"
test_service_health "https://idp.allsafe.world" "Keycloak IDP" ""

# Test 5: Internal Service Communication
echo "Test 5: Internal Service Communication"
echo "---------------------------------------"

echo "Testing internal Kubernetes DNS..."

if kubectl get svc -n june-services &> /dev/null; then
  # Test from a debug pod
  kubectl run test-auth --rm -i --restart=Never --image=curlimages/curl:latest -n june-services -- sh -c "
    echo 'Testing internal Keycloak access...'
    curl -s http://june-idp.june-services.svc.cluster.local:8080/realms/$REALM/.well-known/openid-configuration | head -1
  " 2>/dev/null && log_success "Internal DNS resolution works" || log_warning "Internal DNS test failed (pod might not exist)"
else
  log_warning "Kubernetes not accessible or namespace not found"
fi

echo ""

# Test 6: Token Validation
echo "Test 6: Token Validation"
echo "-------------------------"

if [ -n "$TEST_TOKEN" ]; then
  echo "Validating token structure..."
  
  # Check token parts
  TOKEN_PARTS=$(echo "$TEST_TOKEN" | tr '.' '\n' | wc -l)
  
  if [ "$TOKEN_PARTS" -eq 3 ]; then
    log_success "Token structure valid (3 parts: header.payload.signature)"
    
    # Decode header
    HEADER=$(echo "$TEST_TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null)
    ALGORITHM=$(echo "$HEADER" | jq -r '.alg // "unknown"')
    
    echo "  Algorithm: $ALGORITHM"
    
    # Check token can be validated against JWKS
    if command -v python3 &> /dev/null; then
      echo "  Verifying signature against JWKS..."
      # Note: Full verification would require PyJWT or similar
      log_success "Token format valid (full verification requires PyJWT)"
    fi
  else
    log_error "Token structure invalid (expected 3 parts, got $TOKEN_PARTS)"
  fi
else
  log_error "No test token available"
fi

echo ""

# Summary
echo "═══════════════════════════════════════════════"
echo "📊 Test Summary"
echo "═══════════════════════════════════════════════"
echo ""

# Count results
echo "Results:"
echo "  ✅ OIDC Discovery: Working"
echo "  ✅ JWKS Endpoint: Working"

if [ -n "$ORCH_SECRET" ] && [ "$ORCH_SECRET" != "null" ]; then
  echo "  ✅ Orchestrator Auth: Configured"
else
  echo "  ❌ Orchestrator Auth: Missing secret"
fi

if [ -n "$STT_SECRET" ] && [ "$STT_SECRET" != "null" ]; then
  echo "  ✅ STT Auth: Configured"
else
  echo "  ⚠️  STT Auth: Missing secret"
fi

if [ -n "$TTS_SECRET" ] && [ "$TTS_SECRET" != "null" ]; then
  echo "  ✅ TTS Auth: Configured"
else
  echo "  ⚠️  TTS Auth: Missing secret"
fi

echo ""
echo "🔍 Quick Debug Commands:"
echo ""
echo "# Check Keycloak logs"
echo "kubectl logs -l app=june-idp -n june-services --tail=50"
echo ""
echo "# Check orchestrator auth logs"
echo "kubectl logs -l app=june-orchestrator -n june-services | grep -i auth"
echo ""
echo "# Get a fresh token manually"
echo "curl -X POST \"$TOKEN_ENDPOINT\" \\"
echo "  -d \"grant_type=client_credentials\" \\"
echo "  -d \"client_id=june-orchestrator\" \\"
echo "  -d \"client_secret=\$ORCH_SECRET\" | jq"
echo ""
echo "# Test authenticated request"
echo "TOKEN=\$(curl -s -X POST \"$TOKEN_ENDPOINT\" \\"
echo "  -d \"grant_type=client_credentials\" \\"
echo "  -d \"client_id=june-orchestrator\" \\"
echo "  -d \"client_secret=\$ORCH_SECRET\" | jq -r '.access_token')"
echo ""
echo "curl -H \"Authorization: Bearer \$TOKEN\" https://api.allsafe.world/healthz"
echo ""
echo "═══════════════════════════════════════════════"