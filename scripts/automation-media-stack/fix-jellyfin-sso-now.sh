#!/bin/bash
# One-Command Jellyfin SSO Fix
# This script verifies and fixes Jellyfin SSO configuration automatically

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

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Load configuration
CONFIG_FILE="${ROOT_DIR}/config.env"
if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE"
fi

log "Loading configuration from: $CONFIG_FILE"
source "$CONFIG_FILE"

# Verify required variables
[ -z "$DOMAIN" ] && error "DOMAIN variable is not set in config.env"
[ -z "$KEYCLOAK_URL" ] && error "KEYCLOAK_URL variable is not set in config.env"
[ -z "$KEYCLOAK_ADMIN_USER" ] && error "KEYCLOAK_ADMIN_USER variable is not set in config.env"
[ -z "$KEYCLOAK_ADMIN_PASSWORD" ] && error "KEYCLOAK_ADMIN_PASSWORD variable is not set in config.env"
[ -z "$JELLYFIN_USERNAME" ] && error "JELLYFIN_USERNAME variable is not set in config.env"
[ -z "$JELLYFIN_PASSWORD" ] && error "JELLYFIN_PASSWORD variable is not set in config.env"

JELLYFIN_URL="https://tv.${DOMAIN}"
REALM="${KEYCLOAK_REALM:-allsafe}"

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║        Jellyfin SSO Configuration Fix Tool            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
log "Configuration:"
echo "  Domain: $DOMAIN"
echo "  Jellyfin: $JELLYFIN_URL"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Realm: $REALM"
echo ""

# Step 1: Ensure Keycloak clients are provisioned
log "Step 1: Checking Keycloak OIDC clients..."
echo ""

# Check if we already have client secrets
SSO_CONFIG_FILE="/tmp/media-sso-config.env"

if [ -f "$SSO_CONFIG_FILE" ]; then
    log "Found existing SSO configuration: $SSO_CONFIG_FILE"
    source "$SSO_CONFIG_FILE"
fi

# Provision clients if needed
if [ -z "$JELLYFIN_CLIENT_SECRET" ]; then
    log "Provisioning Keycloak clients..."

    export KEYCLOAK_URL
    export ADMIN_USER="${KEYCLOAK_ADMIN_USER}"
    export ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}"
    export REALM
    export DOMAIN

    SSO_CONFIG_FILE=$(bash "${SCRIPT_DIR}/provision-keycloak-media-sso.sh" 2>&1 | tee /dev/tty | grep -o '/tmp/[^[:space:]]*\.env$' | tail -1)

    if [ -z "$SSO_CONFIG_FILE" ] || [ ! -f "$SSO_CONFIG_FILE" ]; then
        error "Failed to provision Keycloak clients"
    fi

    log "Loading SSO configuration from: $SSO_CONFIG_FILE"
    source "$SSO_CONFIG_FILE"
fi

if [ -z "$JELLYFIN_CLIENT_SECRET" ]; then
    error "JELLYFIN_CLIENT_SECRET not set. Keycloak provisioning may have failed."
fi

success "Keycloak clients configured"
echo ""

# Step 2: Run fully automated SSO setup
log "Step 2: Installing and configuring Jellyfin SSO (fully automated)..."
echo ""

python3 "${SCRIPT_DIR}/install-and-configure-sso-fully-automated.py" \
  --jellyfin-url "$JELLYFIN_URL" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" \
  --keycloak-url "$KEYCLOAK_URL" \
  --realm "$REALM" \
  --client-secret "$JELLYFIN_CLIENT_SECRET" \
  --domain "$DOMAIN"

VERIFY_EXIT_CODE=$?

echo ""

if [ $VERIFY_EXIT_CODE -eq 0 ]; then
    success "Jellyfin SSO is now properly configured!"
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║                   ✅ SSO IS WORKING                     ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "🔑 SSO Login URL:"
    echo "   ${JELLYFIN_URL}/sso/OID/start/keycloak"
    echo ""
    echo "📱 Frontend Integration:"
    echo "   1. REMOVE hardcoded credentials from frontend"
    echo "   2. Redirect users to SSO URL above"
    echo "   3. See docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md for details"
    echo ""
    echo "🧪 Test SSO Now:"
    echo "   Open: ${JELLYFIN_URL}"
    echo "   Click: 'Sign in with Keycloak SSO'"
    echo ""
    echo "📋 User Management:"
    echo "   Assign roles in Keycloak: ${KEYCLOAK_URL}/admin"
    echo "   Required roles:"
    echo "     - jellyfin-admin (for admins)"
    echo "     - jellyfin-user (for users)"
    echo ""
else
    error "SSO setup failed"
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║                 ❌ SSO SETUP FAILED                     ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "Possible issues:"
    echo "  1. Jellyfin not accessible at: ${JELLYFIN_URL}"
    echo "  2. Invalid credentials for Jellyfin"
    echo "  3. Keycloak client secret incorrect"
    echo ""
    echo "🔧 Troubleshooting:"
    echo "  1. Check Jellyfin is running:"
    echo "     kubectl get pods -n media-stack | grep jellyfin"
    echo ""
    echo "  2. Check Jellyfin logs:"
    echo "     kubectl logs -n media-stack deployment/jellyfin"
    echo ""
    echo "  3. Verify Keycloak client secret:"
    echo "     source $SSO_CONFIG_FILE"
    echo "     echo \$JELLYFIN_CLIENT_SECRET"
    echo ""
    echo "  4. Re-run the script:"
    echo "     bash ${SCRIPT_DIR}/fix-jellyfin-sso-now.sh"
    echo ""
fi

# Save configuration for future use
if [ -f "$SSO_CONFIG_FILE" ]; then
    log "Configuration saved to: $SSO_CONFIG_FILE"
    echo ""
    echo "To use in other scripts:"
    echo "  source $SSO_CONFIG_FILE"
fi
