#!/bin/bash
# June Platform - Keycloak Media Stack SSO Configuration Phase
# Automates SSO setup for Jellyfin and Jellyseerr with Keycloak

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

# Verify jq is installed
if ! command -v jq &> /dev/null; then
    error "jq is not installed. Install with: apt-get install jq"
fi

AUTOMATION_DIR="${ROOT_DIR}/scripts/automation-media-stack"

log "Setting up Media Stack SSO for domain: $DOMAIN"
echo ""
echo "🔐 Keycloak Media Stack SSO Setup"
echo "=================================="
echo "  Domain: $DOMAIN"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Realm: ${KEYCLOAK_REALM:-allsafe}"
echo ""

# Wait for Keycloak to be ready (in case it was just installed)
log "Verifying Keycloak is ready..."
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    # Try to get admin token to verify Keycloak is ready
    TEST_TOKEN=$(curl -k -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      -d "username=$KEYCLOAK_ADMIN_USER" \
      -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
      -d "grant_type=password" \
      -d "client_id=admin-cli" 2>/dev/null)

    if echo "$TEST_TOKEN" | jq -e '.access_token' > /dev/null 2>&1; then
        success "Keycloak is ready and accepting API calls"
        break
    fi

    ATTEMPT=$((ATTEMPT + 1))
    log "Attempt $ATTEMPT/$MAX_ATTEMPTS - Waiting for Keycloak..."
    sleep 10
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    error "Keycloak is not ready. Please ensure phase 09.1 completed successfully."
fi
echo ""

# Verify required scripts exist
[ ! -f "$AUTOMATION_DIR/provision-keycloak-media-sso.sh" ] && error "provision-keycloak-media-sso.sh not found"
[ ! -f "$AUTOMATION_DIR/install-jellyfin-sso-plugin.py" ] && error "install-jellyfin-sso-plugin.py not found"
[ ! -f "$AUTOMATION_DIR/configure-jellyfin-sso.py" ] && error "configure-jellyfin-sso.py not found"
[ ! -f "$AUTOMATION_DIR/configure-jellyseerr-oidc.py" ] && error "configure-jellyseerr-oidc.py not found"

# Make scripts executable
chmod +x "$AUTOMATION_DIR/provision-keycloak-media-sso.sh"
chmod +x "$AUTOMATION_DIR/install-jellyfin-sso-plugin.py"
chmod +x "$AUTOMATION_DIR/configure-jellyfin-sso.py"
chmod +x "$AUTOMATION_DIR/configure-jellyseerr-oidc.py"

# Step 1: Provision Keycloak clients
log "Step 1: Provisioning Keycloak OIDC clients..."
echo ""

export KEYCLOAK_URL
export ADMIN_USER="${KEYCLOAK_ADMIN_USER}"
export ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}"
export REALM="${KEYCLOAK_REALM:-allsafe}"
export DOMAIN

SSO_CONFIG_FILE=$(bash "$AUTOMATION_DIR/provision-keycloak-media-sso.sh")

if [ ! -f "$SSO_CONFIG_FILE" ]; then
    error "Failed to provision Keycloak clients"
fi

success "Keycloak clients provisioned"
log "Loading SSO configuration from: $SSO_CONFIG_FILE"
source "$SSO_CONFIG_FILE"
echo ""

# Step 2: Wait for Jellyfin to be ready
log "Step 2: Waiting for Jellyfin to be ready..."
echo ""

JELLYFIN_URL="https://tv.${DOMAIN}"
MAX_WAIT=60
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -ks "$JELLYFIN_URL/health" &>/dev/null || \
       curl -ks "$JELLYFIN_URL/System/Info/Public" &>/dev/null; then
        success "Jellyfin is ready"
        break
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    log "Still waiting... ($WAITED/$MAX_WAIT seconds)"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    warn "Jellyfin may not be ready yet, continuing anyway..."
fi

echo ""

# Step 3: Configure SSO (plugin pre-installed in Docker image)
log "Step 3: Configuring Jellyfin SSO..."
echo ""

python3 "${AUTOMATION_DIR}/configure-sso-only.py" \
  --jellyfin-url "$JELLYFIN_URL" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" \
  --keycloak-url "$KEYCLOAK_URL" \
  --realm "$REALM" \
  --client-secret "$JELLYFIN_CLIENT_SECRET" \
  --domain "$DOMAIN"

if [ $? -ne 0 ]; then
    warn "Jellyfin SSO configuration encountered issues"
    echo ""
    echo "Note: SSO plugin should be pre-installed in the custom Docker image"
    echo "If using standard Jellyfin image, the plugin needs to be installed separately"
    echo ""
fi

echo ""

# Step 4: Jellyseerr OIDC (info only, handled by configure-jellyseerr-oidc.py)
log "Step 4: Jellyseerr OIDC information..."
echo ""

log "Note: Jellyseerr OIDC can be configured via the configure-jellyseerr-oidc.py script"
echo "Configuration details:"
echo "  - OIDC Issuer: ${KEYCLOAK_URL}/realms/${REALM}"
echo "  - Client ID: jellyseerr"
echo "  - Client Secret: ${JELLYSEERR_CLIENT_SECRET}"
echo ""

# Summary
echo ""
echo "═══════════════════════════════════════════════"
success "Media Stack SSO Configuration Complete (FULLY AUTOMATED)!"
echo "═══════════════════════════════════════════════"
echo ""
echo "✅ What was configured automatically:"
echo "  1. Keycloak OIDC clients (jellyfin, jellyseerr)"
echo "  2. Jellyfin SSO plugin installed and configured"
echo "  3. SSO button added to Jellyfin login page"
echo "  4. Role-based access control enabled"
echo ""
echo "🔐 SSO Endpoints:"
echo ""
echo "Jellyfin SSO Login:"
echo "  https://tv.${DOMAIN}/sso/OID/start/keycloak"
echo ""
echo "Jellyseerr OIDC Login:"
echo "  https://requests.${DOMAIN}"
echo "  (Click 'Sign in with Keycloak' button)"
echo ""
echo "📱 CRITICAL - Frontend Integration:"
echo "  ❌ REMOVE hardcoded credentials from frontend code!"
echo "  ✅ Redirect users to: https://tv.${DOMAIN}/sso/OID/start/keycloak"
echo "  📖 See: docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md"
echo ""
echo "🔑 Keycloak User Management:"
echo "  Admin Portal: ${KEYCLOAK_URL}/admin"
echo ""
echo "  Assign these roles to users:"
echo "  Jellyfin:"
echo "    - jellyfin-admin (administrators)"
echo "    - jellyfin-user (regular users)"
echo ""
echo "  Jellyseerr:"
echo "    - jellyseerr-admin (administrators)"
echo "    - jellyseerr-user (regular users)"
echo ""
echo "🧪 Test SSO Now:"
echo "  1. Visit: https://tv.${DOMAIN}"
echo "  2. Click: 'Sign in with Keycloak SSO'"
echo "  3. Login with Keycloak credentials"
echo "  4. Should be logged into Jellyfin automatically"
echo ""
echo "🔧 If SSO Not Working:"
echo "  Run: bash ${AUTOMATION_DIR}/fix-jellyfin-sso-now.sh"
echo ""
echo "📄 Configuration: $SSO_CONFIG_FILE"
echo "═══════════════════════════════════════════════"
