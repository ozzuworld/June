#!/bin/bash
# Keycloak Configuration Automation for June Services (FIXED - No ANSI codes in generated script)
# This script automates the Keycloak setup using the Admin REST API

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

echo "🔐 Keycloak Configuration Automation (FIXED)"
echo "============================================="

# Configuration
read -p "Keycloak URL [https://idp.allsafe.world]: " KEYCLOAK_URL
KEYCLOAK_URL=${KEYCLOAK_URL:-https://idp.allsafe.world}

read -p "Admin username [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

read -sp "Admin password: " ADMIN_PASSWORD
echo ""

read -p "Realm name [allsafe]: " REALM
REALM=${REALM:-allsafe}

log_info "Configuration:"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Admin: $ADMIN_USER"
echo "  Realm: $REALM"
echo ""

# Verify jq is installed
if ! command -v jq &> /dev/null; then
    log_error "jq is not installed. Install with: apt-get install jq"
    exit 1
fi

# Get admin token
log_info "Getting admin access token..."
TOKEN_RESPONSE=$(curl -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$ADMIN_USER" \
  -d "password=$ADMIN_PASSWORD" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

ADMIN_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$ADMIN_TOKEN" ]; then
  log_error "Failed to get admin token. Check credentials."
  echo "Response: $TOKEN_RESPONSE"
  exit 1
fi

log_success "Admin token obtained"

# Create realm
log_info "Creating realm '$REALM'..."
REALM_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM")

if echo "$REALM_CHECK" | jq -e '.realm' > /dev/null 2>&1; then
  log_warning "Realm '$REALM' already exists"
else
  CREATE_REALM=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"realm\": \"$REALM\",
      \"enabled\": true,
      \"displayName\": \"June AI Platform\",
      \"accessTokenLifespan\": 3600,
      \"ssoSessionIdleTimeout\": 1800,
      \"ssoSessionMaxLifespan\": 36000
    }")
  
  HTTP_CODE=$(echo "$CREATE_REALM" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
  
  if [ "$HTTP_CODE" = "201" ]; then
    log_success "Realm '$REALM' created"
  else
    log_error "Failed to create realm (HTTP $HTTP_CODE)"
    echo "$CREATE_REALM"
  fi
fi

# Function to create client and return secret
create_client_with_secret() {
  local CLIENT_ID=$1
  local ROOT_URL=$2
  local REDIRECT_URIS=$3
  
  log_info "Creating client '$CLIENT_ID'..."
  
  # Check if client exists
  CLIENT_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
  
  CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
  
  if [ -n "$CLIENT_UUID" ]; then
    log_warning "Client '$CLIENT_ID' already exists (ID: $CLIENT_UUID)"
  else
    # Create client
    CREATE_CLIENT=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"clientId\": \"$CLIENT_ID\",
        \"enabled\": true,
        \"protocol\": \"openid-connect\",
        \"publicClient\": false,
        \"serviceAccountsEnabled\": true,
        \"directAccessGrantsEnabled\": true,
        \"standardFlowEnabled\": true,
        \"implicitFlowEnabled\": false,
        \"rootUrl\": \"$ROOT_URL\",
        \"redirectUris\": $REDIRECT_URIS,
        \"webOrigins\": [\"*\"],
        \"attributes\": {
          \"access.token.lifespan\": \"3600\",
          \"client.secret.creation.time\": \"$(date +%s)\"
        }
      }")
    
    HTTP_CODE=$(echo "$CREATE_CLIENT" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    
    if [ "$HTTP_CODE" = "201" ]; then
      log_success "Client '$CLIENT_ID' created"
      
      # Get the newly created client UUID
      sleep 2  # Wait for Keycloak to process
      CLIENT_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
      CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
    else
      log_error "Failed to create client '$CLIENT_ID' (HTTP $HTTP_CODE)"
      echo "$CREATE_CLIENT"
      return 1
    fi
  fi
  
  # Get client secret
  if [ -n "$CLIENT_UUID" ]; then
    log_info "Retrieving secret for '$CLIENT_ID'..."
    SECRET_RESPONSE=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")
    
    SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')
    
    if [ -n "$SECRET" ]; then
      log_success "Secret retrieved for '$CLIENT_ID'"
      echo "$CLIENT_UUID|$SECRET"
    else
      log_error "Failed to get secret for '$CLIENT_ID'"
      echo "Response: $SECRET_RESPONSE"
      return 1
    fi
  else
    log_error "Could not find client UUID for '$CLIENT_ID'"
    return 1
  fi
}

# Create clients
log_info "Creating service clients..."

# June Orchestrator
ORCH_RESULT=$(create_client_with_secret "june-orchestrator" "https://api.allsafe.world" \
  '["https://api.allsafe.world/*", "http://localhost:8080/*", "http://june-orchestrator.june-services.svc.cluster.local:8080/*"]')
ORCH_UUID=$(echo "$ORCH_RESULT" | cut -d'|' -f1)
ORCH_SECRET=$(echo "$ORCH_RESULT" | cut -d'|' -f2)

# June STT
STT_RESULT=$(create_client_with_secret "june-stt" "https://stt.allsafe.world" \
  '["https://stt.allsafe.world/*", "http://localhost:8000/*", "http://june-stt.june-services.svc.cluster.local:8000/*"]')
STT_UUID=$(echo "$STT_RESULT" | cut -d'|' -f1)
STT_SECRET=$(echo "$STT_RESULT" | cut -d'|' -f2)

# June TTS
TTS_RESULT=$(create_client_with_secret "june-tts" "https://tts.allsafe.world" \
  '["https://tts.allsafe.world/*", "http://localhost:8000/*", "http://june-tts.june-services.svc.cluster.local:8000/*"]')
TTS_UUID=$(echo "$TTS_RESULT" | cut -d'|' -f1)
TTS_SECRET=$(echo "$TTS_RESULT" | cut -d'|' -f2)

# Verify we got all secrets
if [ -z "$ORCH_SECRET" ] || [ -z "$STT_SECRET" ] || [ -z "$TTS_SECRET" ]; then
  log_error "Failed to retrieve all client secrets!"
  echo ""
  echo "Orchestrator: ${ORCH_SECRET:-MISSING}"
  echo "STT: ${STT_SECRET:-MISSING}"
  echo "TTS: ${TTS_SECRET:-MISSING}"
  exit 1
fi

# Create client scopes
log_info "Creating client scopes..."

create_scope() {
  local SCOPE_NAME=$1
  
  SCOPE_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes")
  
  SCOPE_EXISTS=$(echo "$SCOPE_CHECK" | jq -r ".[] | select(.name==\"$SCOPE_NAME\") | .id")
  
  if [ -n "$SCOPE_EXISTS" ]; then
    log_warning "Scope '$SCOPE_NAME' already exists"
    return
  fi
  
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"$SCOPE_NAME\",
      \"protocol\": \"openid-connect\",
      \"attributes\": {
        \"include.in.token.scope\": \"true\",
        \"display.on.consent.screen\": \"true\"
      }
    }" > /dev/null
  
  log_success "Scope '$SCOPE_NAME' created"
}

create_scope "tts:synthesize"
create_scope "stt:transcribe"
create_scope "orchestrator:webhook"

# Create roles
log_info "Creating realm roles..."

create_role() {
  local ROLE_NAME=$1
  local DESCRIPTION=$2
  
  ROLE_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/roles/$ROLE_NAME")
  
  if echo "$ROLE_CHECK" | jq -e '.name' > /dev/null 2>&1; then
    log_warning "Role '$ROLE_NAME' already exists"
    return
  fi
  
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/roles" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"$ROLE_NAME\",
      \"description\": \"$DESCRIPTION\"
    }" > /dev/null
  
  log_success "Role '$ROLE_NAME' created"
}

create_role "june-user" "Standard June service user"
create_role "june-admin" "June service administrator"
create_role "june-service" "Service-to-service communication"

# Generate kubectl commands (FIXED: No ANSI codes in generated file)
log_info "Generating Kubernetes secret update commands..."

# Use cat with EOF (no variable expansion for the script content)
# Only substitute the actual secret values
cat > update-k8s-secrets.sh << 'SCRIPT_EOF'
#!/bin/bash
# Generated Keycloak secret update commands

echo "🔐 Updating Kubernetes secrets with Keycloak credentials..."

# Update june-orchestrator secrets
kubectl create secret generic june-orchestrator-secrets \
  --from-literal=keycloak-client-id=june-orchestrator \
  --from-literal=keycloak-client-secret=ORCH_SECRET_PLACEHOLDER \
  --from-literal=gemini-api-key=${GEMINI_API_KEY:-AIzaSyA20vz_9eC0Un6lRrkOKUK5vS-u_zNW1uM} \
  -n june-services \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-orchestrator secrets updated"

# Update june-stt secrets
kubectl create secret generic june-stt-secrets \
  --from-literal=keycloak-client-id=june-stt \
  --from-literal=keycloak-client-secret=STT_SECRET_PLACEHOLDER \
  -n june-services \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-stt secrets updated"

# Update june-tts secrets
kubectl create secret generic june-tts-secrets \
  --from-literal=keycloak-client-id=june-tts \
  --from-literal=keycloak-client-secret=TTS_SECRET_PLACEHOLDER \
  -n june-services \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-tts secrets updated"

echo ""
echo "🔄 Restarting services to apply changes..."
kubectl rollout restart deployment/june-orchestrator -n june-services
kubectl rollout restart deployment/june-stt -n june-services
kubectl rollout restart deployment/june-tts -n june-services

echo ""
echo "✅ All secrets updated and services restarted!"
echo ""
echo "🔍 Check status with:"
echo "  kubectl get pods -n june-services"
echo "  kubectl logs -l app=june-orchestrator -n june-services --tail=50"
SCRIPT_EOF

# Now replace the placeholders with actual values
sed -i "s/ORCH_SECRET_PLACEHOLDER/$ORCH_SECRET/g" update-k8s-secrets.sh
sed -i "s/STT_SECRET_PLACEHOLDER/$STT_SECRET/g" update-k8s-secrets.sh
sed -i "s/TTS_SECRET_PLACEHOLDER/$TTS_SECRET/g" update-k8s-secrets.sh

chmod +x update-k8s-secrets.sh

log_success "Kubernetes update script created: update-k8s-secrets.sh"

# Test token generation
log_info "Testing token generation..."
TEST_TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=june-orchestrator" \
  -d "client_secret=$ORCH_SECRET")

if echo "$TEST_TOKEN" | jq -e '.access_token' > /dev/null 2>&1; then
  log_success "Token generation test PASSED"
else
  log_warning "Token generation test FAILED"
  echo "Response: $TEST_TOKEN"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════"
log_success "Keycloak Configuration Complete!"
echo "═══════════════════════════════════════════════"
echo ""
echo "📋 Client Credentials:"
echo ""
echo "june-orchestrator:"
echo "  client_id: june-orchestrator"
echo "  client_secret: $ORCH_SECRET"
echo "  UUID: $ORCH_UUID"
echo ""
echo "june-stt:"
echo "  client_id: june-stt"
echo "  client_secret: $STT_SECRET"
echo "  UUID: $STT_UUID"
echo ""
echo "june-tts:"
echo "  client_id: june-tts"
echo "  client_secret: $TTS_SECRET"
echo "  UUID: $TTS_UUID"
echo ""
echo "🔍 Verify Configuration:"
echo "  1. Access Keycloak admin: $KEYCLOAK_URL/admin"
echo "  2. Check realm: $REALM"
echo "  3. Test token generation:"
echo ""
echo "curl -X POST \"$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token\" \\"
echo "  -d \"grant_type=client_credentials\" \\"
echo "  -d \"client_id=june-orchestrator\" \\"
echo "  -d \"client_secret=$ORCH_SECRET\" | jq"
echo ""
echo "📝 Next Steps:"
echo "  1. ✅ Credentials generated successfully"
echo "  2. Run: ./update-k8s-secrets.sh"
echo "  3. Verify services: kubectl get pods -n june-services"
echo "  4. Test authentication: scripts/keycloak/auth-test.sh"
echo ""
echo "💾 Save these credentials securely!"
echo "═══════════════════════════════════════════════"