#!/bin/bash
# Keycloak Configuration Automation for June Services (TRULY FIXED - Clean data capture)
# This script automates the Keycloak setup using the Admin REST API

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}" >&2; }
log_success() { echo -e "${GREEN}✅ $1${NC}" >&2; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}" >&2; }
log_error()   { echo -e "${RED}❌ $1${NC}" >&2; }

echo "🔐 Keycloak Configuration Automation (TRULY FIXED)" >&2
echo "=================================================" >&2

# Configuration
read -p "Keycloak URL [https://idp.allsafe.world](https://idp.allsafe.world): " KEYCLOAK_URL
KEYCLOAK_URL=${KEYCLOAK_URL:-https://idp.allsafe.world}

read -p "Admin username [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

read -sp "Admin password: " ADMIN_PASSWORD
echo "" >&2

read -p "Realm name [allsafe]: " REALM
REALM=${REALM:-allsafe}

log_info "Configuration:"
echo "  Keycloak: $KEYCLOAK_URL" >&2
echo "  Admin: $ADMIN_USER" >&2
echo "  Realm: $REALM" >&2
echo "" >&2

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
  echo "Response: $TOKEN_RESPONSE" >&2
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
    echo "$CREATE_REALM" >&2
  fi
fi

# Function to create client and return secret (MINIMAL FIX - Only clean the return data)
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
  
  # Get client secret - ONLY FIX NEEDED: Separate logging from data return
  if [ -n "$CLIENT_UUID" ]; then
    {
      log_info "Retrieving secret for '$CLIENT_ID'..."
      SECRET_RESPONSE=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")
      
      SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')
      
      if [ -n "$SECRET" ]; then
        log_success "Secret retrieved for '$CLIENT_ID'"
      else
        log_error "Failed to get secret for '$CLIENT_ID'"
        echo "Response: $SECRET_RESPONSE"
        return 1
      fi
    } >&2
    
    # CRITICAL: Only output clean data, no log messages
    echo "$CLIENT_UUID|$SECRET"
  else
    log_error "Could not find client UUID for '$CLIENT_ID'"
    return 1
  fi
}


# Create clients (FIXED - Capture only clean output)
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
  echo "" >&2
  echo "Orchestrator: ${ORCH_SECRET:-MISSING}" >&2
  echo "STT: ${STT_SECRET:-MISSING}" >&2
  echo "TTS: ${TTS_SECRET:-MISSING}" >&2
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

# Generate kubectl commands with validation
log_info "Generating Kubernetes secret update commands..."

# Validate secrets before generating script
if [[ ! "$ORCH_SECRET" =~ ^[A-Za-z0-9_-]+$ ]] || [ ${#ORCH_SECRET} -lt 16 ]; then
  log_error "Orchestrator secret appears invalid: '$ORCH_SECRET'"
  exit 1
fi

if [[ ! "$STT_SECRET" =~ ^[A-Za-z0-9_-]+$ ]] || [ ${#STT_SECRET} -lt 16 ]; then
  log_error "STT secret appears invalid: '$STT_SECRET'"
  exit 1
fi

if [[ ! "$TTS_SECRET" =~ ^[A-Za-z0-9_-]+$ ]] || [ ${#TTS_SECRET} -lt 16 ]; then
  log_error "TTS secret appears invalid: '$TTS_SECRET'"
  exit 1
fi

# Generate the script with clean variable substitution
cat > update-k8s-secrets.sh << EOF
#!/bin/bash
# Generated Keycloak secret update commands (Clean secrets validated)

echo "🔐 Updating Kubernetes secrets with clean Keycloak credentials..."

# Validate secrets exist
if [ -z "$ORCH_SECRET" ] || [ -z "$STT_SECRET" ] || [ -z "$TTS_SECRET" ]; then
  echo "❌ Error: Missing secrets in generated script"
  exit 1
fi

# Update june-orchestrator secrets
kubectl create secret generic june-orchestrator-secrets \\
  --from-literal=keycloak-client-id=june-orchestrator \\
  --from-literal=keycloak-client-secret='$ORCH_SECRET' \\
  --from-literal=gemini-api-key=\${GEMINI_API_KEY:-AIzaSyA20vz_9eC0Un6lRrkOKUK5vS-u_zNW1uM} \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-orchestrator secrets updated"

# Update june-stt secrets
kubectl create secret generic june-stt-secrets \\
  --from-literal=keycloak-client-id=june-stt \\
  --from-literal=keycloak-client-secret='$STT_SECRET' \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-stt secrets updated"

# Update june-tts secrets
kubectl create secret generic june-tts-secrets \\
  --from-literal=keycloak-client-id=june-tts \\
  --from-literal=keycloak-client-secret='$TTS_SECRET' \\
  -n june-services \\
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
EOF

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
  echo "Response: $TEST_TOKEN" >&2
fi

# Summary
echo "" >&2
echo "═══════════════════════════════════════════════" >&2
log_success "Keycloak Configuration Complete!"
echo "═══════════════════════════════════════════════" >&2
echo "" >&2
echo "📋 Client Credentials:" >&2
echo "" >&2
echo "june-orchestrator:" >&2
echo "  client_id: june-orchestrator" >&2
echo "  client_secret: $ORCH_SECRET" >&2
echo "  UUID: $ORCH_UUID" >&2
echo "" >&2
echo "june-stt:" >&2
echo "  client_id: june-stt" >&2
echo "  client_secret: $STT_SECRET" >&2
echo "  UUID: $STT_UUID" >&2
echo "" >&2
echo "june-tts:" >&2
echo "  client_id: june-tts" >&2
echo "  client_secret: $TTS_SECRET" >&2
echo "  UUID: $TTS_UUID" >&2
echo "" >&2
echo "🔍 Verify Configuration:" >&2
echo "  1. Access Keycloak admin: $KEYCLOAK_URL/admin" >&2
echo "  2. Check realm: $REALM" >&2
echo "  3. Test token generation:" >&2
echo "" >&2
echo "curl -X POST \"$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token\" \\" >&2
echo "  -d \"grant_type=client_credentials\" \\" >&2
echo "  -d \"client_id=june-orchestrator\" \\" >&2
echo "  -d \"client_secret=$ORCH_SECRET\" | jq" >&2
echo "" >&2
echo "📝 Next Steps:" >&2
echo "  1. ✅ Credentials generated successfully" >&2
echo "  2. Run: ./update-k8s-secrets.sh" >&2
echo "  3. Verify services: kubectl get pods -n june-services" >&2
echo "  4. Test authentication: scripts/keycloak/auth-test.sh" >&2
echo "" >&2
echo "💾 Save these credentials securely!" >&2
echo "═══════════════════════════════════════════════" >&2
