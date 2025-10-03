#!/bin/bash
# Keycloak Configuration Automation for June Services
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

echo "🔐 Keycloak Configuration Automation"
echo "====================================="

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
ADMIN_TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$ADMIN_USER" \
  -d "password=$ADMIN_PASSWORD" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" | jq -r '.access_token')

if [ "$ADMIN_TOKEN" = "null" ] || [ -z "$ADMIN_TOKEN" ]; then
  log_error "Failed to get admin token. Check credentials."
  exit 1
fi

log_success "Admin token obtained"

# Create realm
log_info "Creating realm '$REALM'..."
REALM_EXISTS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM" | jq -r '.realm // empty')

if [ -z "$REALM_EXISTS" ]; then
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

# Function to create client
create_client() {
  local CLIENT_ID=$1
  local ROOT_URL=$2
  local REDIRECT_URIS=$3
  
  log_info "Creating client '$CLIENT_ID'..."
  
  # Check if client exists
  CLIENT_EXISTS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID" | jq -r '.[0].id // empty')
  
  if [ -n "$CLIENT_EXISTS" ]; then
    log_warning "Client '$CLIENT_ID' already exists (ID: $CLIENT_EXISTS)"
    echo "$CLIENT_EXISTS"
    return
  fi
  
  # Create client
  RESPONSE=$(curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
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
  
  # Get client ID
  CLIENT_UUID=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID" | jq -r '.[0].id')
  
  if [ -n "$CLIENT_UUID" ] && [ "$CLIENT_UUID" != "null" ]; then
    log_success "Client '$CLIENT_ID' created (ID: $CLIENT_UUID)"
    echo "$CLIENT_UUID"
  else
    log_error "Failed to create client '$CLIENT_ID'"
    return 1
  fi
}

# Function to get client secret
get_client_secret() {
  local CLIENT_UUID=$1
  local CLIENT_NAME=$2
  
  SECRET=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret" | jq -r '.value')
  
  if [ -n "$SECRET" ] && [ "$SECRET" != "null" ]; then
    log_success "Client secret for $CLIENT_NAME: $SECRET"
    echo "$SECRET"
  else
    log_error "Failed to get secret for $CLIENT_NAME"
  fi
}

# Create clients
log_info "Creating service clients..."

# June Orchestrator
ORCH_UUID=$(create_client "june-orchestrator" "https://api.allsafe.world" \
  '["https://api.allsafe.world/*", "http://localhost:8080/*"]')
ORCH_SECRET=$(get_client_secret "$ORCH_UUID" "june-orchestrator")

# June STT
STT_UUID=$(create_client "june-stt" "https://stt.allsafe.world" \
  '["https://stt.allsafe.world/*", "http://localhost:8000/*"]')
STT_SECRET=$(get_client_secret "$STT_UUID" "june-stt")

# June TTS
TTS_UUID=$(create_client "june-tts" "https://tts.allsafe.world" \
  '["https://tts.allsafe.world/*", "http://localhost:8000/*"]')
TTS_SECRET=$(get_client_secret "$TTS_UUID" "june-tts")

# Create client scopes
log_info "Creating client scopes..."

create_scope() {
  local SCOPE_NAME=$1
  
  SCOPE_EXISTS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" | jq -r ".[] | select(.name==\"$SCOPE_NAME\") | .id")
  
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
    }"
  
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
  
  ROLE_EXISTS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/roles/$ROLE_NAME" | jq -r '.name // empty')
  
  if [ -n "$ROLE_EXISTS" ]; then
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

# Add audience mapper to clients
log_info "Adding audience mappers..."

add_audience_mapper() {
  local CLIENT_UUID=$1
  local CLIENT_NAME=$2
  
  # Get dedicated scope ID
  DEDICATED_SCOPE=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/default-client-scopes" | \
    jq -r ".[] | select(.name==\"${CLIENT_NAME}-dedicated\") | .id")
  
  if [ -z "$DEDICATED_SCOPE" ]; then
    log_warning "No dedicated scope found for $CLIENT_NAME"
    return
  fi
  
  # Add audience mapper
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes/$DEDICATED_SCOPE/protocol-mappers/models" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"audience-mapper\",
      \"protocol\": \"openid-connect\",
      \"protocolMapper\": \"oidc-audience-mapper\",
      \"config\": {
        \"included.client.audience\": \"$CLIENT_NAME\",
        \"id.token.claim\": \"true\",
        \"access.token.claim\": \"true\"
      }
    }"
  
  log_success "Audience mapper added to $CLIENT_NAME"
}

add_audience_mapper "$ORCH_UUID" "june-orchestrator"
add_audience_mapper "$STT_UUID" "june-stt"
add_audience_mapper "$TTS_UUID" "june-tts"

# Generate kubectl commands
log_info "Generating Kubernetes secret update commands..."

cat > update-k8s-secrets.sh << EOF
#!/bin/bash
# Generated Keycloak secret update commands

# Update june-orchestrator secrets
kubectl create secret generic june-orchestrator-secrets \\
  --from-literal=keycloak-client-id=june-orchestrator \\
  --from-literal=keycloak-client-secret=$ORCH_SECRET \\
  --from-literal=gemini-api-key=\${GEMINI_API_KEY:-AIzaSyA20vz_9eC0Un6lRrkOKUK5vS-u_zNW1uM} \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

# Update june-stt secrets
kubectl create secret generic june-stt-secrets \\
  --from-literal=keycloak-client-id=june-stt \\
  --from-literal=keycloak-client-secret=$STT_SECRET \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

# Update june-tts secrets
kubectl create secret generic june-tts-secrets \\
  --from-literal=keycloak-client-id=june-tts \\
  --from-literal=keycloak-client-secret=$TTS_SECRET \\
  -n june-services \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ Secrets updated!"
echo ""
echo "Now restart services:"
echo "  kubectl rollout restart deployment/june-orchestrator -n june-services"
echo "  kubectl rollout restart deployment/june-stt -n june-services"
echo "  kubectl rollout restart deployment/june-tts -n june-services"
EOF

chmod +x update-k8s-secrets.sh

log_success "Kubernetes update script created: update-k8s-secrets.sh"

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
echo ""
echo "june-stt:"
echo "  client_id: june-stt"
echo "  client_secret: $STT_SECRET"
echo ""
echo "june-tts:"
echo "  client_id: june-tts"
echo "  client_secret: $TTS_SECRET"
echo ""
echo "🔍 Verify Configuration:"
echo "  1. Check realm: $KEYCLOAK_URL/admin/master/console/#/$REALM"
echo "  2. Test token generation:"
echo ""
echo "     curl -X POST \"$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token\" \\"
echo "       -d \"grant_type=client_credentials\" \\"
echo "       -d \"client_id=june-orchestrator\" \\"
echo "       -d \"client_secret=$ORCH_SECRET\""
echo ""
echo "📝 Next Steps:"
echo "  1. Review the credentials above"
echo "  2. Run: ./update-k8s-secrets.sh"
echo "  3. Restart services to apply changes"
echo ""
echo "═══════════════════════════════════════════════"