#!/bin/bash
# June Platform - Phase 4.6.1: Headscale OIDC Configuration
# Configure Keycloak OIDC client for Headscale VPN authentication

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration
CONFIG_FILE="${ROOT_DIR}/config.env"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# Validate required variables
if [ -z "$DOMAIN" ]; then
    error "DOMAIN is not set in config.env"
fi

if [ -z "$KEYCLOAK_URL" ]; then
    error "KEYCLOAK_URL is not set in config.env"
fi

if [ -z "$KEYCLOAK_ADMIN_USER" ]; then
    error "KEYCLOAK_ADMIN_USER is not set in config.env"
fi

if [ -z "$KEYCLOAK_ADMIN_PASSWORD" ]; then
    error "KEYCLOAK_ADMIN_PASSWORD is not set in config.env"
fi

# Default values
REALM="${KEYCLOAK_REALM:-allsafe}"
CLIENT_ID="headscale-vpn"
HEADSCALE_URL="https://headscale.${DOMAIN}"
REDIRECT_URI="${HEADSCALE_URL}/oidc/callback"

header "Configuring Keycloak OIDC Client for Headscale"

# Wait for Keycloak to be ready
log "Checking Keycloak availability..."
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -k -s -f "$KEYCLOAK_URL/health/ready" > /dev/null 2>&1 || \
       curl -k -s "$KEYCLOAK_URL/realms/master" | grep -q "realm" 2>/dev/null; then
        success "Keycloak is ready"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    log "Attempt $ATTEMPT/$MAX_ATTEMPTS - Waiting for Keycloak..."
    sleep 5
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    error "Keycloak is not available"
fi

# Verify jq is installed
if ! command -v jq &> /dev/null; then
    error "jq is not installed. Install with: apt-get install jq"
fi

# Get admin token
log "Getting admin access token..."
TOKEN_RESPONSE=$(curl -k -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

ADMIN_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$ADMIN_TOKEN" ]; then
    error "Failed to get admin token. Response: $TOKEN_RESPONSE"
fi

success "Admin token obtained"

# Check if realm exists
log "Verifying realm '$REALM' exists..."
REALM_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM")

if ! echo "$REALM_CHECK" | jq -e '.realm' > /dev/null 2>&1; then
    error "Realm '$REALM' does not exist. Please run Keycloak provisioning first."
fi

success "Realm '$REALM' found"

# Check if client already exists
log "Checking if Headscale OIDC client exists..."
CLIENT_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")

CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')

if [ -n "$CLIENT_UUID" ]; then
    warn "Client '$CLIENT_ID' already exists (ID: $CLIENT_UUID)"
    log "Updating existing client configuration..."

    # Update the client with correct settings
    UPDATE_CLIENT=$(curl -k -s -w "\nHTTP_CODE:%{http_code}" -X PUT \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"clientId\": \"$CLIENT_ID\",
        \"enabled\": true,
        \"protocol\": \"openid-connect\",
        \"publicClient\": false,
        \"serviceAccountsEnabled\": false,
        \"directAccessGrantsEnabled\": false,
        \"standardFlowEnabled\": true,
        \"implicitFlowEnabled\": false,
        \"rootUrl\": \"$HEADSCALE_URL\",
        \"redirectUris\": [\"$REDIRECT_URI\"],
        \"webOrigins\": [\"$HEADSCALE_URL\"],
        \"attributes\": {
          \"pkce.code.challenge.method\": \"S256\",
          \"access.token.lifespan\": \"86400\"
        },
        \"protocolMappers\": [
          {
            \"name\": \"email\",
            \"protocol\": \"openid-connect\",
            \"protocolMapper\": \"oidc-usermodel-property-mapper\",
            \"consentRequired\": false,
            \"config\": {
              \"userinfo.token.claim\": \"true\",
              \"user.attribute\": \"email\",
              \"id.token.claim\": \"true\",
              \"access.token.claim\": \"true\",
              \"claim.name\": \"email\",
              \"jsonType.label\": \"String\"
            }
          },
          {
            \"name\": \"email_verified\",
            \"protocol\": \"openid-connect\",
            \"protocolMapper\": \"oidc-usermodel-property-mapper\",
            \"consentRequired\": false,
            \"config\": {
              \"userinfo.token.claim\": \"true\",
              \"user.attribute\": \"emailVerified\",
              \"id.token.claim\": \"true\",
              \"access.token.claim\": \"true\",
              \"claim.name\": \"email_verified\",
              \"jsonType.label\": \"boolean\"
            }
          }
        ]
      }")

    HTTP_CODE=$(echo "$UPDATE_CLIENT" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

    if [ "$HTTP_CODE" = "204" ] || [ "$HTTP_CODE" = "200" ]; then
        success "Client '$CLIENT_ID' updated"
    else
        error "Failed to update client (HTTP $HTTP_CODE)"
    fi
else
    log "Creating new Headscale OIDC client..."

    CREATE_CLIENT=$(curl -k -s -w "\nHTTP_CODE:%{http_code}" -X POST \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"clientId\": \"$CLIENT_ID\",
        \"enabled\": true,
        \"protocol\": \"openid-connect\",
        \"publicClient\": false,
        \"serviceAccountsEnabled\": false,
        \"directAccessGrantsEnabled\": false,
        \"standardFlowEnabled\": true,
        \"implicitFlowEnabled\": false,
        \"rootUrl\": \"$HEADSCALE_URL\",
        \"redirectUris\": [\"$REDIRECT_URI\"],
        \"webOrigins\": [\"$HEADSCALE_URL\"],
        \"attributes\": {
          \"pkce.code.challenge.method\": \"S256\",
          \"access.token.lifespan\": \"86400\"
        },
        \"protocolMappers\": [
          {
            \"name\": \"email\",
            \"protocol\": \"openid-connect\",
            \"protocolMapper\": \"oidc-usermodel-property-mapper\",
            \"consentRequired\": false,
            \"config\": {
              \"userinfo.token.claim\": \"true\",
              \"user.attribute\": \"email\",
              \"id.token.claim\": \"true\",
              \"access.token.claim\": \"true\",
              \"claim.name\": \"email\",
              \"jsonType.label\": \"String\"
            }
          },
          {
            \"name\": \"email_verified\",
            \"protocol\": \"openid-connect\",
            \"protocolMapper\": \"oidc-usermodel-property-mapper\",
            \"consentRequired\": false,
            \"config\": {
              \"userinfo.token.claim\": \"true\",
              \"user.attribute\": \"emailVerified\",
              \"id.token.claim\": \"true\",
              \"access.token.claim\": \"true\",
              \"claim.name\": \"email_verified\",
              \"jsonType.label\": \"boolean\"
            }
          }
        ]
      }")

    HTTP_CODE=$(echo "$CREATE_CLIENT" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

    if [ "$HTTP_CODE" = "201" ]; then
        success "Client '$CLIENT_ID' created"
        sleep 2

        # Get the newly created client UUID
        CLIENT_CHECK=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
          "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID")
        CLIENT_UUID=$(echo "$CLIENT_CHECK" | jq -r '.[0].id // empty')
    else
        error "Failed to create client (HTTP $HTTP_CODE): $CREATE_CLIENT"
    fi
fi

# Get client secret
if [ -n "$CLIENT_UUID" ]; then
    log "Retrieving client secret..."

    SECRET_RESPONSE=$(curl -k -s -H "Authorization: Bearer $ADMIN_TOKEN" \
      "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")

    CLIENT_SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.value // empty')

    if [ -z "$CLIENT_SECRET" ]; then
        # Try to regenerate the secret if it doesn't exist
        log "Regenerating client secret..."
        REGEN_RESPONSE=$(curl -k -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
          "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret")

        CLIENT_SECRET=$(echo "$REGEN_RESPONSE" | jq -r '.value // empty')
    fi

    if [ -n "$CLIENT_SECRET" ]; then
        success "Client secret retrieved"
    else
        error "Failed to get client secret"
    fi
fi

# Create Kubernetes secret for Headscale OIDC configuration
log "Creating Kubernetes secret for Headscale OIDC..."

HEADSCALE_NAMESPACE="${HEADSCALE_NAMESPACE:-headscale}"

kubectl create secret generic headscale-oidc \
  -n "$HEADSCALE_NAMESPACE" \
  --from-literal=client-id="$CLIENT_ID" \
  --from-literal=client-secret="$CLIENT_SECRET" \
  --from-literal=issuer="$KEYCLOAK_URL/realms/$REALM" \
  --dry-run=client -o yaml | kubectl apply -f -

success "Kubernetes secret created"

# Display summary
header "Headscale OIDC Configuration Complete"

echo "🔐 Keycloak OIDC Client Configuration:"
echo "  Client ID:       $CLIENT_ID"
echo "  Client Secret:   $CLIENT_SECRET"
echo "  Issuer URL:      $KEYCLOAK_URL/realms/$REALM"
echo "  Redirect URI:    $REDIRECT_URI"
echo ""
echo "✅ Kubernetes Secret Created:"
echo "  Name:            headscale-oidc"
echo "  Namespace:       $HEADSCALE_NAMESPACE"
echo ""
echo "📝 OIDC Configuration for Headscale config.yaml:"
echo ""
echo "oidc:"
echo "  only_start_if_oidc_is_available: true"
echo "  issuer: \"$KEYCLOAK_URL/realms/$REALM\""
echo "  client_id: \"$CLIENT_ID\""
echo "  client_secret: \"$CLIENT_SECRET\""
echo "  scope: [\"openid\", \"profile\", \"email\"]"
echo "  allowed_domains: [\"$DOMAIN\"]  # Optional: restrict to your domain"
echo "  strip_email_domain: false"
echo ""
echo "📋 Next Steps:"
echo "  1. Update Headscale ConfigMap with OIDC settings"
echo "  2. Restart Headscale deployment"
echo "  3. Test OIDC login flow: tailscale up --login-server=$HEADSCALE_URL"
echo ""
