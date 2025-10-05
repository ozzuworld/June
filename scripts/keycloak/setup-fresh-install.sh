#!/bin/bash
# Keycloak Configuration Automation for June Services (TRULY FIXED - Clean data capture)
# This script automates the Keycloak setup using the Admin REST API
# Includes: Frontend "june-mobile-app" public PKCE client + orchestrator-aud scope

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
read -p "Keycloak URL [https://idp.ozzu.world](https://idp.ozzu.world): " KEYCLOAK_URL
KEYCLOAK_URL=${KEYCLOAK_URL:-https://idp.ozzu.world}

read -p "Admin username [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

read -sp "Admin password: " ADMIN_PASSWORD
echo "" >&2

read -p "Realm name [allsafe]: " REALM
REALM=${REALM:-allsafe}

# Frontend (mobile) client config
FRONTEND_CLIENT_ID_DEFAULT="june-mobile-app"
read -p "Frontend clientId [${FRONTEND_CLIENT_ID_DEFAULT}]: " FRONTEND_CLIENT_ID
FRONTEND_CLIENT_ID=${FRONTEND_CLIENT_ID:-$FRONTEND_CLIENT_ID_DEFAULT}

# Native / Expo redirect URIs (comma-separated if multiple)
# Your app.json shows scheme 'june' and path 'auth/callback' -> june://auth/callback
read -p "Frontend redirect URIs (comma-separated) [june://auth/callback]: " FRONTEND_REDIRECTS_CSV
FRONTEND_REDIRECTS_CSV=${FRONTEND_REDIRECTS_CSV:-june://auth/callback}

# Optionally allow Expo web preview (set to 'y' to include https://auth.expo.io/*)
read -p "Include Expo web preview origin? [y/N]: " INCLUDE_EXPO
INCLUDE_EXPO=${INCLUDE_EXPO:-N}

# API audience name to include in access tokens for the app to call orchestrator
API_AUDIENCE_DEFAULT="june-orchestrator"
read -p "API audience to include in tokens [${API_AUDIENCE_DEFAULT}]: " API_AUDIENCE
API_AUDIENCE=${API_AUDIENCE:-$API_AUDIENCE_DEFAULT}

AUD_SCOPE_DEFAULT="orchestrator-aud"
read -p "Audience client-scope name [${AUD_SCOPE_DEFAULT}]: " AUD_SCOPE
AUD_SCOPE=${AUD_SCOPE:-$AUD_SCOPE_DEFAULT}

log_info "Configuration:"
echo "  Keycloak: $KEYCLOAK_URL" >&2
echo "  Admin: $ADMIN_USER" >&2
echo "  Realm: $REALM" >&2
echo "  Frontend clientId: $FRONTEND_CLIENT_ID" >&2
echo "  Frontend redirects: $FRONTEND_REDIRECTS_CSV" >&2
echo "  Audience scope: $AUD_SCOPE (aud: $API_AUDIENCE)" >&2
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

# Function to create confidential client and return secret (unchanged)
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

# === NEW: Create Public PKCE Frontend Client (no secret) ===
create_public_pkce_client() {
  local CLIENT_ID="$1"
  local REDIRECTS_CSV="$2"
  local INCLUDE_EXPO="$3"

  # Build JSON array for redirectUris from comma-separated input
  IFS=',' read -ra ARR <<< "$REDIRECTS_CSV"
  local REDIRECTS_JSON="["
  for i in "${!ARR[@]}"; do
    uri="$(echo "${ARR[$i]}" | xargs)"
    [ -z "$uri" ] && continue
    REDIRECTS_JSON+="\"$uri\""
    if [ $i -lt $((${#ARR[@]}-1)) ]; then
      REDIRECTS_JSON+=","
    fi
  done
  REDIRECTS_JSON+="]"

  log_info "Creating public PKCE client '$CLIENT_ID' with redirects: $REDIRECTS_JSON"

  # Check if client exists
  CLIENT_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
  CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')

  if [ -n "$CLIENT_UUID" ]; then
    log_warning "Client '$CLIENT_ID' already exists (ID: $CLIENT_UUID)"
  else
    # Construct webOrigins
    WEB_ORIGINS="[]"
    if [[ "$INCLUDE_EXPO" =~ ^[Yy]$ ]]; then
      WEB_ORIGINS="[\"https://auth.expo.io\"]"
    fi

    CREATE_CLIENT=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"clientId\": \"$CLIENT_ID\",
        \"enabled\": true,
        \"protocol\": \"openid-connect\",
        \"publicClient\": true,
        \"standardFlowEnabled\": true,
        \"directAccessGrantsEnabled\": false,
        \"serviceAccountsEnabled\": false,
        \"redirectUris\": $REDIRECTS_JSON,
        \"webOrigins\": $WEB_ORIGINS,
        \"attributes\": {
          \"pkce.code.challenge.method\": \"S256\"
        }
      }")

    HTTP_CODE=$(echo "$CREATE_CLIENT" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    if [ "$HTTP_CODE" = "201" ]; then
      log_success "Public PKCE client '$CLIENT_ID' created"
      sleep 1
      CLIENT_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
      CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
    else
      log_error "Failed to create public client '$CLIENT_ID' (HTTP $HTTP_CODE)"
      echo "$CREATE_CLIENT" >&2
      return 1
    fi
  fi

  if [ -z "$CLIENT_UUID" ]; then
    log_error "Unable to resolve client UUID for '$CLIENT_ID'"
    return 1
  fi

  echo "$CLIENT_UUID"
}

# === NEW: Create audience client-scope (adds aud: API_AUDIENCE) ===
create_audience_scope() {
  local SCOPE_NAME="$1"
  local AUDIENCE="$2"

  # Find or create scope
  SCOPE_ID=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" | jq -r ".[] | select(.name==\"$SCOPE_NAME\") | .id")

  if [ -n "$SCOPE_ID" ]; then
    log_warning "Scope '$SCOPE_NAME' already exists"
  else
    SCOPE_CREATE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" \
      -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
      -d "{
        \"name\": \"$SCOPE_NAME\",
        \"protocol\": \"openid-connect\",
        \"attributes\": {
          \"include.in.token.scope\": \"true\",
          \"display.on.consent.screen\": \"true\"
        }
      }")
    HTTP_CODE=$(echo "$SCOPE_CREATE" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    if [ "$HTTP_CODE" != "201" ]; then
      log_error "Failed to create scope '$SCOPE_NAME' (HTTP $HTTP_CODE)"
      echo "$SCOPE_CREATE" >&2
      return 1
    fi
    log_success "Scope '$SCOPE_NAME' created"
    SCOPE_ID=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
      "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" | jq -r ".[] | select(.name==\"$SCOPE_NAME\") | .id")
  fi

  # Ensure Audience mapper exists
  MAPPERS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes/$SCOPE_ID/protocol-mappers/models")

  HAS_AUD=$(echo "$MAPPERS" | jq -r ".[] | select(.protocolMapper==\"oidc-audience-mapper\") | .config.\"included.client.audience\" | select(.==\"$AUDIENCE\")")
  if [ -n "$HAS_AUD" ]; then
    log_warning "Audience mapper for '$AUDIENCE' already present in scope '$SCOPE_NAME'"
  else
    ADD_MAP=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes/$SCOPE_ID/protocol-mappers/models" \
      -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
      -d "{
        \"name\": \"aud-$AUDIENCE\",
        \"protocol\": \"openid-connect\",
        \"protocolMapper\": \"oidc-audience-mapper\",
        \"config\": {
          \"included.client.audience\": \"$AUDIENCE\",
          \"id.token.claim\": \"true\",
          \"access.token.claim\": \"true\"
        }
      }")
    HTTP_CODE=$(echo "$ADD_MAP" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    if [ "$HTTP_CODE" != "201" ]; then
      log_error "Failed to add audience mapper (HTTP $HTTP_CODE)"
      echo "$ADD_MAP" >&2
      return 1
    fi
    log_success "Audience mapper added to scope '$SCOPE_NAME' (aud: $AUDIENCE)"
  fi

  echo "$SCOPE_ID"
}

# === ORIGINAL: Create service clients (confidential) ===
log_info "Creating service clients..."

# June Orchestrator
ORCH_RESULT=$(create_client_with_secret "june-orchestrator" "https://api.ozzu.world" \
  '["https://api.ozzu.world/*", "http://localhost:8080/*", "http://june-orchestrator.june-services.svc.cluster.local:8080/*"]')
ORCH_UUID=$(echo "$ORCH_RESULT" | cut -d'|' -f1)
ORCH_SECRET=$(echo "$ORCH_RESULT" | cut -d'|' -f2)

# June STT
STT_RESULT=$(create_client_with_secret "june-stt" "https://stt.ozzu.world" \
  '["https://stt.ozzu.world/*", "http://localhost:8000/*", "http://june-stt.june-services.svc.cluster.local:8000/*"]')
STT_UUID=$(echo "$STT_RESULT" | cut -d'|' -f1)
STT_SECRET=$(echo "$STT_RESULT" | cut -d'|' -f2)

# June TTS
TTS_RESULT=$(create_client_with_secret "june-tts" "https://tts.ozzu.world" \
  '["https://tts.ozzu.world/*", "http://localhost:8000/*", "http://june-tts.june-services.svc.cluster.local:8000/*"]')
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

# ORIGINAL: Create simple scopes (still kept)
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

# ORIGINAL: Create roles
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

# === NEW: Create audience scope & Frontend public client, then assign scope ===
log_info "Ensuring audience scope '$AUD_SCOPE' (aud: $API_AUDIENCE) exists..."
AUD_SCOPE_ID=$(create_audience_scope "$AUD_SCOPE" "$API_AUDIENCE")

log_info "Creating/ensuring frontend public PKCE client '$FRONTEND_CLIENT_ID'..."
FRONTEND_UUID=$(create_public_pkce_client "$FRONTEND_CLIENT_ID" "$FRONTEND_REDIRECTS_CSV" "$INCLUDE_EXPO")

# ✅ CRITICAL FIX: Assign the audience scope as DEFAULT (not optional)
log_info "Assigning scope '$AUD_SCOPE' to client '$FRONTEND_CLIENT_ID' (default)..."
ASSIGN_DEFAULT_RESULT=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
  "$KEYCLOAK_URL/admin/realms/$REALM/clients/$FRONTEND_UUID/default-client-scopes/$AUD_SCOPE_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

if [ "$ASSIGN_DEFAULT_RESULT" = "204" ] || [ "$ASSIGN_DEFAULT_RESULT" = "201" ]; then
  log_success "Scope '$AUD_SCOPE' assigned to client as DEFAULT scope"
else
  log_warning "Default scope assignment failed (HTTP $ASSIGN_DEFAULT_RESULT), trying optional..."
  
  # Fallback: try optional assignment
  ASSIGN_OPTIONAL_RESULT=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$FRONTEND_UUID/optional-client-scopes/$AUD_SCOPE_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN")
    
  if [ "$ASSIGN_OPTIONAL_RESULT" = "204" ] || [ "$ASSIGN_OPTIONAL_RESULT" = "201" ]; then
    log_success "Scope '$AUD_SCOPE' assigned to client as OPTIONAL scope"
    log_warning "NOTE: Your app must explicitly request 'orchestrator-aud' scope"
  else
    log_error "Both default and optional scope assignments failed!"
    log_error "Default: HTTP $ASSIGN_DEFAULT_RESULT, Optional: HTTP $ASSIGN_OPTIONAL_RESULT"
    exit 1
  fi
fi

# === ORIGINAL: Generate Kubernetes secret update script for confidential clients ===
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
kubectl create secret generic june-orchestrator-secrets \
  --from-literal=keycloak-client-id=june-orchestrator \
  --from-literal=keycloak-client-secret='$ORCH_SECRET' \
  --from-literal=gemini-api-key=\${GEMINI_API_KEY:-CHANGEME} \
  -n june-services \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-orchestrator secrets updated"

# Update june-stt secrets
kubectl create secret generic june-stt-secrets \
  --from-literal=keycloak-client-id=june-stt \
  --from-literal=keycloak-client-secret='$STT_SECRET' \
  -n june-services \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ june-stt secrets updated"

# Update june-tts secrets
kubectl create secret generic june-tts-secrets \
  --from-literal=keycloak-client-id=june-tts \
  --from-literal=keycloak-client-secret='$TTS_SECRET' \
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
EOF

chmod +x update-k8s-secrets.sh
log_success "Kubernetes update script created: update-k8s-secrets.sh"

# Test token generation for orchestrator (client credentials)
log_info "Testing token generation (client_credentials) for 'june-orchestrator'..."
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

# ✅ CRITICAL: Test frontend client token generation with orchestrator-aud scope
log_info "Testing frontend client scope availability..."
FRONTEND_TEST=$(curl -s "$KEYCLOAK_URL/realms/$REALM/.well-known/openid-configuration")
if echo "$FRONTEND_TEST" | jq -e '.scopes_supported[] | select(.=="orchestrator-aud")' > /dev/null 2>&1; then
  log_success "orchestrator-aud scope is available in realm"
else
  log_warning "orchestrator-aud scope may not be properly exposed"
fi

# Show frontend summary (no secret)
echo "" >&2
echo "═══════════════════════════════════════════════" >&2
log_success "Keycloak Configuration Complete!"
echo "═══════════════════════════════════════════════" >&2
echo "" >&2
echo "📋 Service Client Credentials:" >&2
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
echo "📱 Frontend Client (Public PKCE):" >&2
echo "  client_id: $FRONTEND_CLIENT_ID" >&2
echo "  UUID: $FRONTEND_UUID" >&2
echo "  Redirect URIs: $FRONTEND_REDIRECTS_CSV" >&2
echo "  Scope assigned: $AUD_SCOPE (aud: $API_AUDIENCE)" >&2
echo "" >&2
echo "🔍 Verify Configuration:" >&2
echo "  1. Admin: $KEYCLOAK_URL/admin" >&2
echo "  2. Discovery: $KEYCLOAK_URL/realms/$REALM/.well-known/openid-configuration" >&2
echo "" >&2
echo "📝 Next Steps:" >&2
echo "  1. Run: ./update-k8s-secrets.sh" >&2
echo "  2. In your app, ensure:" >&2
echo "     - REALM='${REALM}'" >&2
echo "     - CLIENT_ID='${FRONTEND_CLIENT_ID}'" >&2
echo "     - redirectUri scheme matches (e.g., june://auth/callback)" >&2
echo "     - request scopes include: openid profile email ${AUD_SCOPE}" >&2
echo "" >&2
echo "💾 Save credentials securely." >&2
echo "═══════════════════════════════════════════════" >&2
