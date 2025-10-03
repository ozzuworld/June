#!/bin/bash
# Fixed Keycloak Configuration for June Services
# Handles client creation and secret retrieval properly

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

echo "🔐 Fixed Keycloak Configuration Script"
echo "======================================="

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
  log_error "Failed to get admin token"
  echo "Response: $TOKEN_RESPONSE"
  exit 1
fi

log_success "Admin token obtained"

# Check if realm exists
log_info "Checking realm '$REALM'..."
REALM_CHECK=$(curl -s -w "%{http_code}" -o /tmp/realm_check.json \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM")

if [ "$REALM_CHECK" = "404" ]; then
  log_info "Creating realm '$REALM'..."
  curl -s -X POST "$KEYCLOAK_URL/admin/realms" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"realm\": \"$REALM\",
      \"enabled\": true,
      \"displayName\": \"June AI Platform\",
      \"accessTokenLifespan\": 3600,
      \"ssoSessionIdleTimeout\": 1800,
      \"ssoSessionMaxLifespan\": 36000
    }"
  log_success "Realm '$REALM' created"
else
  log_warning "Realm '$REALM' already exists"
fi

# Function to create or update client
create_or_update_client() {
  local CLIENT_ID=$1
  local ROOT_URL=$2
  local REDIRECT_URIS=$3
  
  log_info "Processing client '$CLIENT_ID'..."
  
  # Check if client exists
  CLIENT_LIST=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
  
  CLIENT_UUID=$(echo "$CLIENT_LIST" | jq -r '.[0].id // empty')
  
  if [ -n "$CLIENT_UUID" ]; then
    log_warning "Client '$CLIENT_ID' exists (UUID: $CLIENT_UUID)"
    
    # Update existing client
    curl -s -X PUT "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"id\": \"$CLIENT_UUID\",
        \"clientId\": \"$CLIENT_ID\",
        \"enabled\": true,
        \"protocol\": \"openid-connect\",
        \"publicClient\": false,
        \"serviceAccountsEnabled\": true,
        \"directAccessGrantsEnabled\": true,
        \"standardFlowEnabled\": true,
        \"rootUrl\": \"$ROOT_URL\",
        \"redirectUris\": $REDIRECT_URIS,
        \"webOrigins\": [\"*\"],
        \"attributes\": {
          \"access.token.lifespan\": \"3600\"
        }
      }"
    
    log_success "Client '$CLIENT_ID' updated"
  else
    log_info "Creating new client '$CLIENT_ID'..."
    
    # Create new client
    CREATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
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
        \"rootUrl\": \"$ROOT_URL\",
        \"redirectUris\": $REDIRECT_URIS,
        \"webOrigins\": [\"*\"],
        \"attributes\": {
          \"access.token.lifespan\": \"3600\"
        }
      }")
    
    HTTP_CODE=$(echo "$CREATE_RESPONSE" | tail -n1)
    
    if [ "$HTTP_CODE" = "201" ]; then
      log_success "Client '$CLIENT_ID' created"
      
      # Get the UUID of newly created client
      sleep 2
      CLIENT_LIST=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
      CLIENT_UUID=$(echo "$CLIENT_LIST" | jq -r '.[0].id // empty')
    else
      log_error "Failed to create client (HTTP $HTTP_CODE)"
      return 1
    fi
  fi
  
  echo "$CLIENT_UUID"
}

# Function to get or regenerate client secret
get_client_secret() {
  local CLIENT_UUID=$1
  local CLIENT_NAME=$2
  
  log_info "Getting secret for '$CLIENT_NAME'..."
  
  # Try to get existing secret
  SECRET_RESPONSE=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")
  
  SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')
  
  if [ -z "$SECRET" ]; then
    log_warning "No secret found, regenerating..."
    
    # Regenerate secret
    SECRET_RESPONSE=$(curl -s -X POST \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")
    
    SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')
  fi
  
  if [ -n "$SECRET" ]; then
    log_success "Secret obtained for '$CLIENT_NAME'"
    echo "$SECRET"
  else
    log_error "Failed to get secret for '$CLIENT_NAME'"
    echo "Response: $SECRET_RESPONSE" >&2
    return 1
  fi
}

# Create/update clients and get secrets
log_info "Setting up service clients..."
echo ""

# June Orchestrator
log_info "=== June Orchestrator ==="
ORCH_UUID=$(create_or_update_client "june-orchestrator" "https://api.allsafe.world" \
  '["https://api.allsafe.world/*", "http://localhost:8080/*"]')

if [ -n "$ORCH_UUID" ]; then
  ORCH_SECRET=$(get_client_secret "$ORCH_UUID" "june-orchestrator")
else
  log_error "Failed to get Orchestrator client UUID"
fi

echo ""

# June STT
log_info "=== June STT ==="
STT_UUID=$(create_or_update_client "june-stt" "https://stt.allsafe.world" \
  '["https://stt.allsafe.world/*", "http://localhost:8000/*"]')

if [ -n "$STT_UUID" ]; then
  STT_SECRET=$(get_client_secret "$STT_UUID" "june-stt")
else
  log_error "Failed to get STT client UUID"
fi

echo ""

# June TTS
log_info "=== June TTS ==="
TTS_UUID=$(create_or_update_client "june-tts" "https://tts.allsafe.world" \
  '["https://tts.allsafe.world/*", "http://localhost:8000/*"]')

if [ -n "$TTS_UUID" ]; then
  TTS_SECRET=$(get_client_secret "$TTS_UUID" "june-tts")
else
  log_error "Failed to get TTS client UUID"
fi

echo ""

# Verify all secrets were obtained
if [ -z "$ORCH_SECRET" ] || [ -z "$STT_SECRET" ] || [ -z "$TTS_SECRET" ]; then
  log_error "Failed to obtain all client secrets"
  echo ""
  echo "Partial results:"
  echo "  Orchestrator: ${ORCH_SECRET:-FAILED}"
  echo "  STT: ${STT_SECRET:-FAILED}"
  echo "  TTS: ${TTS_SECRET:-FAILED}"
  exit 1
fi

# Create client scopes
log_info "Creating client scopes..."

create_scope() {
  local SCOPE_NAME=$1
  
  SCOPE_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" | \
    jq -r ".[] | select(.name==\"$SCOPE_NAME\") | .id")
  
  if [ -n "$SCOPE_CHECK" ]; then
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
    }"
  
  log_success "Scope '$SCOPE_NAME' created"
}

create_scope "tts:synthesize"
create_scope "stt:transcribe"
create_scope "orchestrator:webhook"

# Create realm roles
log_info "Creating realm roles..."

create_role() {
  local ROLE_NAME=$1
  local DESCRIPTION=$2
  
  ROLE_CHECK=$(curl -s -w "%{http_code}" -o /dev/null \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/roles/$ROLE_NAME")
  
  if [ "$ROLE_CHECK" = "200" ]; then
    log_warning "Role '$ROLE_NAME' already exists"
    return
  fi
  
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/roles" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"$ROLE_NAME\",
      \"description\": \"$DESCRIPTION\"
    }"
  
  log_success "Role '$ROLE_NAME' created"
}

create_role "june-user" "Standard June service user"
create_role "june-admin" "June service administrator"
create_role "june-service" "Service-to-service communication"

# Generate Kubernetes update script
log_info "Generating Kubernetes secret update script..."

cat > update-k8s-secrets.sh << EOF
#!/bin/bash
# Generated Keycloak Secret Update Script
# Run this to update Kubernetes secrets with Keycloak credentials

set -e

echo "🔐 Updating Kubernetes Secrets for June Services"
echo "================================================"

# Check if we're connected to the cluster
if ! kubectl cluster-info &> /dev/null; then
  echo "❌ Cannot connect to Kubernetes cluster"
  exit 1
fi

# Check if namespace exists
if ! kubectl get namespace june-services &> /dev/null; then
  echo "❌ Namespace 'june-services' not found"
  exit 1
fi

echo "✅ Connected to Kubernetes cluster"
echo ""

# Update june-orchestrator secrets
echo "Updating june-orchestrator secrets..."
kubectl create secret generic june-orchestrator-secrets \\
  --from-literal=keycloak-client-id=june-orchestrator \\
  --from-literal=keycloak-client-secret='$ORCH_SECRET' \\
  --from-literal=keycloak-realm=allsafe \\
  --from-literal=keycloak-url=https://idp.allsafe.world \\
  --from-literal=gemini-api-key=\${GEMINI_API_KEY:-AIzaSyA20vz_9eC0Un6lRrkOKUK5vS-u_zNW1uM} \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-orchestrator secrets updated"

# Update june-stt secrets
echo "Updating june-stt secrets..."
kubectl create secret generic june-stt-secrets \\
  --from-literal=keycloak-client-id=june-stt \\
  --from-literal=keycloak-client-secret='$STT_SECRET' \\
  --from-literal=keycloak-realm=allsafe \\
  --from-literal=keycloak-url=https://idp.allsafe.world \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-stt secrets updated"

# Update june-tts secrets
echo "Updating june-tts secrets..."
kubectl create secret generic june-tts-secrets \\
  --from-literal=keycloak-client-id=june-tts \\
  --from-literal=keycloak-client-secret='$TTS_SECRET' \\
  --from-literal=keycloak-realm=allsafe \\
  --from-literal=keycloak-url=https://idp.allsafe.world \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-tts secrets updated"

echo ""
echo "🔄 Restarting services to apply new credentials..."
kubectl rollout restart deployment/june-orchestrator -n june-services
kubectl rollout restart deployment/june-stt -n june-services
kubectl rollout restart deployment/june-tts -n june-services

echo ""
echo "⏳ Waiting for rollouts to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=120s
kubectl rollout status deployment/june-stt -n june-services --timeout=120s
kubectl rollout status deployment/june-tts -n june-services --timeout=120s

echo ""
echo "✅ All secrets updated and services restarted!"
echo ""
echo "🧪 Test authentication:"
echo "  TOKEN=\\\$(curl -s -X POST 'https://idp.allsafe.world/realms/allsafe/protocol/openid-connect/token' \\\\"
echo "    -d 'grant_type=client_credentials' \\\\"
echo "    -d 'client_id=june-orchestrator' \\\\"
echo "    -d 'client_secret=$ORCH_SECRET' | jq -r '.access_token')"
echo ""
echo "  curl -H \"Authorization: Bearer \\\$TOKEN\" https://api.allsafe.world/healthz"
EOF

chmod +x update-k8s-secrets.sh

log_success "Script created: update-k8s-secrets.sh"

# Create verification script
cat > verify-keycloak.sh << EOF
#!/bin/bash
# Verify Keycloak Setup

echo "🧪 Keycloak Configuration Verification"
echo "======================================"

KEYCLOAK_URL="$KEYCLOAK_URL"
REALM="$REALM"

echo "Testing OIDC discovery..."
curl -s "\$KEYCLOAK_URL/realms/\$REALM/.well-known/openid-connect-configuration" | jq '.issuer'

echo ""
echo "Testing client credentials for june-orchestrator..."
TOKEN_RESPONSE=\$(curl -s -X POST "\$KEYCLOAK_URL/realms/\$REALM/protocol/openid-connect/token" \\
  -d "grant_type=client_credentials" \\
  -d "client_id=june-orchestrator" \\
  -d "client_secret=$ORCH_SECRET")

if echo "\$TOKEN_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
  echo "✅ Token obtained successfully"
  echo "\$TOKEN_RESPONSE" | jq .
else
  echo "❌ Token request failed"
  echo "\$TOKEN_RESPONSE"
fi
EOF

chmod +x verify-keycloak.sh

log_success "Script created: verify-keycloak.sh"

# Summary
echo ""
echo "═══════════════════════════════════════════════════════"
log_success "Keycloak Configuration Complete!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "📋 Client Credentials Created:"
echo ""
echo "june-orchestrator:"
echo "  Client ID: june-orchestrator"
echo "  Client Secret: $ORCH_SECRET"
echo "  UUID: $ORCH_UUID"
echo ""
echo "june-stt:"
echo "  Client ID: june-stt"
echo "  Client Secret: $STT_SECRET"
echo "  UUID: $STT_UUID"
echo ""
echo "june-tts:"
echo "  Client ID: june-tts"
echo "  Client Secret: $TTS_SECRET"
echo "  UUID: $TTS_UUID"
echo ""
echo "🔍 OIDC Endpoints:"
echo "  Discovery: $KEYCLOAK_URL/realms/$REALM/.well-known/openid-configure"
echo "  Token: $KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token"
echo "  JWKS: $KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/certs"
echo ""
echo "📝 Next Steps:"
echo "  1. Run: ./update-k8s-secrets.sh"
echo "     This will update all Kubernetes secrets and restart services"
echo ""
echo "  2. Run: ./verify-keycloak.sh"
echo "     This will test token generation"
echo ""
echo "  3. Check service logs:"
echo "     kubectl logs -l app=june-orchestrator -n june-services --tail=50"
echo ""
echo "═══════════════════════════════════════════════════════"