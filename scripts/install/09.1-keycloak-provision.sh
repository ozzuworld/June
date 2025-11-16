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
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    # Check if Keycloak responds (try health endpoints or main page)
    if curl -k -s -f "$KEYCLOAK_URL/health/ready" > /dev/null 2>&1 || \
       curl -k -s -f "$KEYCLOAK_URL/health" > /dev/null 2>&1 || \
       curl -k -s "$KEYCLOAK_URL/realms/master" | grep -q "realm" 2>/dev/null; then
        success "Keycloak is ready"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    log "Attempt $ATTEMPT/$MAX_ATTEMPTS - Waiting for Keycloak..."
    sleep 10
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    error "Keycloak did not become ready in time"
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

success "Keycloak realm provisioned"
echo ""
echo "🔐 Keycloak Configuration:"
echo "  URL: $KEYCLOAK_URL"
echo "  Realm: $REALM"
echo "  Admin User: $KEYCLOAK_ADMIN_USER"
echo ""
echo "✅ Realm '$REALM' is ready"
echo ""
echo "📝 Next Steps:"
echo "  Media stack SSO clients (Jellyfin, Jellyseerr) will be created in phase 09.5"
echo "  For mobile app clients, run: bash scripts/keycloak/setup-fresh-install.sh"
echo ""
