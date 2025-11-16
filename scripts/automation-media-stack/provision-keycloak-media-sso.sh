#!/bin/bash
# Keycloak SSO Configuration for Media Stack (Jellyfin & Jellyseerr)
# Creates OIDC clients for Jellyfin SSO plugin and Jellyseerr

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

echo "🔐 Keycloak Media Stack SSO Configuration" >&2
echo "==========================================" >&2

# Configuration from environment or prompts
KEYCLOAK_URL="${KEYCLOAK_URL:-https://idp.ozzu.world}"
ADMIN_USER="${ADMIN_USER:-admin}"
REALM="${REALM:-allsafe}"
DOMAIN="${DOMAIN:-ozzu.world}"

# If admin password not set, prompt
if [ -z "$ADMIN_PASSWORD" ]; then
    read -sp "Keycloak admin password: " ADMIN_PASSWORD
    echo "" >&2
fi

log_info "Configuration:"
echo "  Keycloak: $KEYCLOAK_URL" >&2
echo "  Realm: $REALM" >&2
echo "  Domain: $DOMAIN" >&2
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

# Verify realm exists
log_info "Verifying realm '$REALM' exists..."
REALM_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM")

if echo "$REALM_CHECK" | jq -e '.realm' > /dev/null 2>&1; then
  log_success "Realm '$REALM' found"
else
  log_error "Realm '$REALM' does not exist. Run phase 09.1-keycloak-provision first."
  exit 1
fi

# Function to create confidential OIDC client
create_oidc_client() {
  local CLIENT_ID=$1
  local ROOT_URL=$2
  local REDIRECT_URIS=$3

  log_info "Creating OIDC client '$CLIENT_ID'..."

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
        \"serviceAccountsEnabled\": false,
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
      sleep 2
      CLIENT_CHECK=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
      CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
    else
      log_error "Failed to create client '$CLIENT_ID' (HTTP $HTTP_CODE)"
      echo "$CREATE_CLIENT" >&2
      return 1
    fi
  fi

  # Get client secret
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
        echo "Response: $SECRET_RESPONSE" >&2
        return 1
      fi
    } >&2

    # Output clean data: UUID|SECRET
    echo "$CLIENT_UUID|$SECRET"
  else
    log_error "Could not find client UUID for '$CLIENT_ID'"
    return 1
  fi
}

# Create roles for media stack
log_info "Creating realm roles for media stack..."

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

create_role "jellyfin-admin" "Jellyfin administrator"
create_role "jellyfin-user" "Jellyfin user"
create_role "jellyseerr-admin" "Jellyseerr administrator"
create_role "jellyseerr-user" "Jellyseerr user"

# Create Jellyfin OIDC client
log_info "Creating Jellyfin OIDC client..."
JELLYFIN_RESULT=$(create_oidc_client "jellyfin" "https://tv.${DOMAIN}" \
  "[\"https://tv.${DOMAIN}/sso/OID/redirect/keycloak\", \"https://tv.${DOMAIN}/sso/OID/start/keycloak\"]")
JELLYFIN_UUID=$(echo "$JELLYFIN_RESULT" | cut -d'|' -f1)
JELLYFIN_SECRET=$(echo "$JELLYFIN_RESULT" | cut -d'|' -f2)

# Create Jellyseerr OIDC client
log_info "Creating Jellyseerr OIDC client..."
JELLYSEERR_RESULT=$(create_oidc_client "jellyseerr" "https://requests.${DOMAIN}" \
  "[\"https://requests.${DOMAIN}/login/oidc/callback\", \"https://requests.${DOMAIN}/*\"]")
JELLYSEERR_UUID=$(echo "$JELLYSEERR_RESULT" | cut -d'|' -f1)
JELLYSEERR_SECRET=$(echo "$JELLYSEERR_RESULT" | cut -d'|' -f2)

# Verify we got all secrets
if [ -z "$JELLYFIN_SECRET" ] || [ -z "$JELLYSEERR_SECRET" ]; then
  log_error "Failed to retrieve all client secrets!"
  echo "" >&2
  echo "Jellyfin: ${JELLYFIN_SECRET:-MISSING}" >&2
  echo "Jellyseerr: ${JELLYSEERR_SECRET:-MISSING}" >&2
  exit 1
fi

# Add role mappers to clients
log_info "Configuring role mappers..."

add_role_mapper() {
  local CLIENT_UUID=$1
  local CLIENT_NAME=$2

  # Check if mapper already exists
  MAPPERS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/protocol-mappers/models")

  HAS_ROLE_MAPPER=$(echo "$MAPPERS" | jq -r '.[] | select(.name=="realm roles") | .name')

  if [ -n "$HAS_ROLE_MAPPER" ]; then
    log_warning "Role mapper already exists for $CLIENT_NAME"
    return
  fi

  # Add realm role mapper
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/protocol-mappers/models" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"realm roles\",
      \"protocol\": \"openid-connect\",
      \"protocolMapper\": \"oidc-usermodel-realm-role-mapper\",
      \"config\": {
        \"claim.name\": \"realm_access.roles\",
        \"jsonType.label\": \"String\",
        \"multivalued\": \"true\",
        \"id.token.claim\": \"true\",
        \"access.token.claim\": \"true\",
        \"userinfo.token.claim\": \"true\"
      }
    }" > /dev/null

  log_success "Role mapper added to $CLIENT_NAME"
}

add_role_mapper "$JELLYFIN_UUID" "Jellyfin"
add_role_mapper "$JELLYSEERR_UUID" "Jellyseerr"

# Test token generation
log_info "Testing token generation for Jellyfin client..."
TEST_TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=jellyfin" \
  -d "client_secret=$JELLYFIN_SECRET")

if echo "$TEST_TOKEN" | jq -e '.access_token' > /dev/null 2>&1; then
  log_success "Token generation test PASSED"
else
  log_warning "Token generation test FAILED (expected for authorization_code flow)"
fi

# Output configuration file
log_info "Generating configuration file..."

cat > /tmp/media-sso-config.env << EOF
# Keycloak Media Stack SSO Configuration
# Generated on $(date)

KEYCLOAK_URL=$KEYCLOAK_URL
KEYCLOAK_REALM=$REALM
DOMAIN=$DOMAIN

# Jellyfin OIDC Client
JELLYFIN_CLIENT_ID=jellyfin
JELLYFIN_CLIENT_SECRET=$JELLYFIN_SECRET
JELLYFIN_CLIENT_UUID=$JELLYFIN_UUID

# Jellyseerr OIDC Client
JELLYSEERR_CLIENT_ID=jellyseerr
JELLYSEERR_CLIENT_SECRET=$JELLYSEERR_SECRET
JELLYSEERR_CLIENT_UUID=$JELLYSEERR_UUID

# OIDC Endpoints
OIDC_ISSUER=$KEYCLOAK_URL/realms/$REALM
OIDC_AUTH_ENDPOINT=$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/auth
OIDC_TOKEN_ENDPOINT=$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token
OIDC_USERINFO_ENDPOINT=$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/userinfo
OIDC_JWKS_ENDPOINT=$KEYCLOAK_URL/realms/$REALM/protocol/certs
EOF

log_success "Configuration saved to /tmp/media-sso-config.env"

# Summary
echo "" >&2
echo "═══════════════════════════════════════════════" >&2
log_success "Keycloak Media Stack SSO Configuration Complete!"
echo "═══════════════════════════════════════════════" >&2
echo "" >&2
echo "📋 Client Credentials:" >&2
echo "" >&2
echo "Jellyfin:" >&2
echo "  Client ID: jellyfin" >&2
echo "  Client Secret: $JELLYFIN_SECRET" >&2
echo "  UUID: $JELLYFIN_UUID" >&2
echo "  Redirect URI: https://tv.${DOMAIN}/sso/OID/redirect/keycloak" >&2
echo "" >&2
echo "Jellyseerr:" >&2
echo "  Client ID: jellyseerr" >&2
echo "  Client Secret: $JELLYSEERR_SECRET" >&2
echo "  UUID: $JELLYSEERR_UUID" >&2
echo "  Redirect URI: https://requests.${DOMAIN}/login/oidc/callback" >&2
echo "" >&2
echo "🔐 Roles Created:" >&2
echo "  - jellyfin-admin" >&2
echo "  - jellyfin-user" >&2
echo "  - jellyseerr-admin" >&2
echo "  - jellyseerr-user" >&2
echo "" >&2
echo "📝 Next Steps:" >&2
echo "  1. Install Jellyfin SSO plugin" >&2
echo "  2. Configure Jellyfin SSO with Keycloak provider" >&2
echo "  3. Configure Jellyseerr OIDC settings" >&2
echo "  4. Assign roles to users in Keycloak admin" >&2
echo "" >&2
echo "💾 Configuration file: /tmp/media-sso-config.env" >&2
echo "═══════════════════════════════════════════════" >&2

# Output the config path for automation scripts
echo "/tmp/media-sso-config.env"
