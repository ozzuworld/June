#!/bin/bash
# June Platform - Keycloak Realm Provisioning Phase
# Creates Keycloak realm and base June service clients

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

ROOT_DIR="$1"

if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    CONFIG_FILE="${ROOT_DIR}/config.env"
    [ ! -f "$CONFIG_FILE" ] && error "Configuration file not found: $CONFIG_FILE"
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set."
[ -z "$KEYCLOAK_URL" ] && error "KEYCLOAK_URL variable is not set."
[ -z "$KEYCLOAK_ADMIN_USER" ] && error "KEYCLOAK_ADMIN_USER variable is not set."
[ -z "$KEYCLOAK_ADMIN_PASSWORD" ] && error "KEYCLOAK_ADMIN_PASSWORD variable is not set."

log "Provisioning Keycloak realm and base clients for domain: $DOMAIN"

# Wait for Keycloak to be ready
log "Waiting for Keycloak to be ready..."
MAX_ATTEMPTS=60  # 10 minutes max wait for fresh installs
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    # Check if Keycloak responds (try health endpoints or main page)
    if curl -k -s -f "$KEYCLOAK_URL/health/ready" > /dev/null 2>&1 || \
       curl -k -s -f "$KEYCLOAK_URL/health" > /dev/null 2>&1 || \
       curl -k -s "$KEYCLOAK_URL/realms/master" | grep -q "realm" 2>/dev/null; then
        success "Keycloak is responding"

        # Give Keycloak extra time to fully initialize on fresh installs
        log "Waiting 30 seconds for Keycloak to fully initialize..."
        sleep 30

        # Verify we can actually get an admin token before proceeding
        log "Testing admin token endpoint..."
        TEST_TOKEN=$(curl -k -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
          -H "Content-Type: application/x-www-form-urlencoded" \
          -d "username=$KEYCLOAK_ADMIN_USER" \
          -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
          -d "grant_type=password" \
          -d "client_id=admin-cli" 2>/dev/null)

        if echo "$TEST_TOKEN" | jq -e '.access_token' > /dev/null 2>&1; then
            success "Keycloak is fully ready and accepting API calls"
            break
        else
            log "Keycloak responded but admin API not ready yet, continuing to wait..."
        fi
    fi
    ATTEMPT=$((ATTEMPT + 1))
    log "Attempt $ATTEMPT/$MAX_ATTEMPTS - Waiting for Keycloak..."
    sleep 10
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    error "Keycloak did not become ready in time (waited 10 minutes)"
fi

# Provision Keycloak realm and clients directly via API
log "Running Keycloak realm and client provisioning..."

# Set defaults
REALM="${KEYCLOAK_REALM:-allsafe}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER}"
ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}"

# Verify jq is installed
if ! command -v jq &> /dev/null; then
    error "jq is not installed. Install with: apt-get install jq"
fi

# Get admin token
log "Getting admin access token..."
TOKEN_RESPONSE=$(curl -k -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$ADMIN_USER" \
  -d "password=$ADMIN_PASSWORD" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

ADMIN_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$ADMIN_TOKEN" ]; then
  error "Failed to get admin token. Response: $TOKEN_RESPONSE"
fi

success "Admin token obtained"

# Create realm if it doesn't exist
log "Creating realm '$REALM'..."
REALM_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM")

if echo "$REALM_CHECK" | jq -e '.realm' > /dev/null 2>&1; then
  warn "Realm '$REALM' already exists"
else
  CREATE_REALM=$(curl -k -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms" \
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
    success "Realm '$REALM' created"
  else
    error "Failed to create realm (HTTP $HTTP_CODE): $CREATE_REALM"
  fi
fi

# Function to create confidential client with secret
create_client_with_secret() {
  local CLIENT_ID=$1
  local ROOT_URL=$2
  local REDIRECT_URIS=$3

  log "Creating client '$CLIENT_ID'..."

  # Check if client exists
  CLIENT_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")

  CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')

  if [ -n "$CLIENT_UUID" ]; then
    warn "Client '$CLIENT_ID' already exists (ID: $CLIENT_UUID)"
  else
    # Create client
    CREATE_CLIENT=$(curl -k -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
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
      success "Client '$CLIENT_ID' created"
      sleep 2
      CLIENT_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
      CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
    else
      error "Failed to create client '$CLIENT_ID' (HTTP $HTTP_CODE)"
    fi
  fi

  # Get client secret
  if [ -n "$CLIENT_UUID" ]; then
    SECRET_RESPONSE=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")

    SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')

    if [ -n "$SECRET" ]; then
      success "Secret retrieved for '$CLIENT_ID'"
      echo "$CLIENT_UUID|$SECRET"
    else
      error "Failed to get secret for '$CLIENT_ID'"
    fi
  fi
}

# Function to create public PKCE client (for mobile app)
create_public_pkce_client() {
  local CLIENT_ID=$1
  local REDIRECT_URIS=$2

  log "Creating public PKCE client '$CLIENT_ID'..."

  # Check if client exists
  CLIENT_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
  CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')

  if [ -n "$CLIENT_UUID" ]; then
    warn "Client '$CLIENT_ID' already exists (ID: $CLIENT_UUID)"
  else
    CREATE_CLIENT=$(curl -k -s -w "\nHTTP_CODE:%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
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
        \"redirectUris\": $REDIRECT_URIS,
        \"webOrigins\": [\"https://auth.expo.io\"],
        \"attributes\": {
          \"pkce.code.challenge.method\": \"S256\"
        }
      }")

    HTTP_CODE=$(echo "$CREATE_CLIENT" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    if [ "$HTTP_CODE" = "201" ]; then
      success "Public PKCE client '$CLIENT_ID' created"
    else
      error "Failed to create public client '$CLIENT_ID' (HTTP $HTTP_CODE)"
    fi
  fi
}

# Create June service clients
log "Creating June service clients..."

# June Orchestrator
ORCH_RESULT=$(create_client_with_secret "june-orchestrator" "https://api.${DOMAIN}" \
  "[\"https://api.${DOMAIN}/*\", \"http://localhost:8080/*\", \"http://june-orchestrator.june-services.svc.cluster.local:8080/*\"]")
ORCH_SECRET=$(echo "$ORCH_RESULT" | cut -d'|' -f2)

# June STT
STT_RESULT=$(create_client_with_secret "june-stt" "https://stt.${DOMAIN}" \
  "[\"https://stt.${DOMAIN}/*\", \"http://localhost:8000/*\", \"http://june-stt.june-services.svc.cluster.local:8000/*\"]")
STT_SECRET=$(echo "$STT_RESULT" | cut -d'|' -f2)

# June TTS
TTS_RESULT=$(create_client_with_secret "june-tts" "https://tts.${DOMAIN}" \
  "[\"https://tts.${DOMAIN}/*\", \"http://localhost:8000/*\", \"http://june-tts.june-services.svc.cluster.local:8000/*\"]")
TTS_SECRET=$(echo "$TTS_RESULT" | cut -d'|' -f2)

# June Mobile App (PKCE public client)
create_public_pkce_client "june-mobile-app" "[\"june://auth/callback\", \"exp://localhost:8081\", \"https://auth.expo.io/@your-username/your-app\"]"

success "Keycloak realm and base clients provisioned"
echo ""
echo "🔐 Keycloak Configuration:"
echo "  URL: $KEYCLOAK_URL"
echo "  Realm: $REALM"
echo "  Admin User: $KEYCLOAK_ADMIN_USER"
echo ""
echo "✅ June Service Clients Created:"
echo "  - june-orchestrator"
echo "  - june-stt"
echo "  - june-tts"
echo "  - june-mobile-app (PKCE)"
echo ""
echo "📝 Client Secrets (save these securely):"
echo "  june-orchestrator: $ORCH_SECRET"
echo "  june-stt: $STT_SECRET"
echo "  june-tts: $TTS_SECRET"
echo ""
echo "📝 Next Steps:"
echo "  1. Update Kubernetes secrets with client secrets"
echo "  2. Media stack SSO clients will be created in phase 09.5"
echo ""
