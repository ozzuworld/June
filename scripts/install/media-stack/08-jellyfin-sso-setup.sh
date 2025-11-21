#!/bin/bash
# Media Stack - Jellyfin SSO Automated Setup
# Fully automated SSO plugin installation and configuration
# Called after Jellyfin is installed and Keycloak is configured

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Please run from June project directory"
fi

if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set. Please check your config.env file."
[ -z "$KEYCLOAK_URL" ] && error "KEYCLOAK_URL variable is not set."
[ -z "$KEYCLOAK_ADMIN_USER" ] && error "KEYCLOAK_ADMIN_USER variable is not set."
[ -z "$KEYCLOAK_ADMIN_PASSWORD" ] && error "KEYCLOAK_ADMIN_PASSWORD variable is not set."
[ -z "$JELLYFIN_USERNAME" ] && error "JELLYFIN_USERNAME variable is not set."
[ -z "$JELLYFIN_PASSWORD" ] && error "JELLYFIN_PASSWORD variable is not set."

JELLYFIN_URL="https://tv.${DOMAIN}"
REALM="${KEYCLOAK_REALM:-allsafe}"
AUTOMATION_DIR="${ROOT_DIR}/scripts/automation-media-stack"

log "Setting up Jellyfin SSO (fully automated)"
echo ""
echo "🔐 Jellyfin SSO Automated Setup"
echo "================================"
echo "  Jellyfin: $JELLYFIN_URL"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Realm: $REALM"
echo ""

# Wait for Jellyfin to be ready
log "Waiting for Jellyfin to be ready..."
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
    error "Jellyfin did not become ready in time"
fi

echo ""

# Provision Keycloak clients first
log "Provisioning Keycloak OIDC clients..."
export KEYCLOAK_URL
export ADMIN_USER="${KEYCLOAK_ADMIN_USER}"
export ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}"
export REALM
export DOMAIN

SSO_CONFIG_FILE=$(bash "${AUTOMATION_DIR}/provision-keycloak-media-sso.sh" 2>&1 | tee /dev/tty | grep -o '/tmp/[^[:space:]]*\.env$' | tail -1)

if [ -z "$SSO_CONFIG_FILE" ] || [ ! -f "$SSO_CONFIG_FILE" ]; then
    error "Failed to provision Keycloak clients"
fi

log "Loading SSO configuration from: $SSO_CONFIG_FILE"
source "$SSO_CONFIG_FILE"

if [ -z "$JELLYFIN_CLIENT_SECRET" ]; then
    error "JELLYFIN_CLIENT_SECRET not set. Keycloak provisioning failed."
fi

success "Keycloak clients provisioned"
echo ""

# Run fully automated SSO setup
log "Running fully automated SSO setup..."
echo ""

python3 "${AUTOMATION_DIR}/install-and-configure-sso-fully-automated.py" \
  --jellyfin-url "$JELLYFIN_URL" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" \
  --keycloak-url "$KEYCLOAK_URL" \
  --realm "$REALM" \
  --client-secret "$JELLYFIN_CLIENT_SECRET" \
  --domain "$DOMAIN"

if [ $? -eq 0 ]; then
    success "Jellyfin SSO configured successfully!"
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║           ✅ JELLYFIN SSO IS NOW ENABLED!              ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "🔑 SSO Login URL:"
    echo "   ${JELLYFIN_URL}/sso/OID/start/keycloak"
    echo ""
    echo "📱 Frontend Integration:"
    echo "   - Remove hardcoded credentials from frontend"
    echo "   - Redirect to SSO URL above"
    echo "   - See: docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md"
    echo ""
    echo "👥 User Management:"
    echo "   Assign roles in Keycloak: ${KEYCLOAK_URL}/admin"
    echo "   - jellyfin-admin (for admins)"
    echo "   - jellyfin-user (for users)"
    echo ""
else
    warn "SSO setup encountered issues, but may have partially succeeded"
    echo ""
    echo "Try running the fix script manually:"
    echo "  bash ${AUTOMATION_DIR}/fix-jellyfin-sso-now.sh"
    echo ""
fi

# Save config to a permanent location
PERM_CONFIG="${ROOT_DIR}/config/jellyfin-sso.env"
mkdir -p "${ROOT_DIR}/config"
cp "$SSO_CONFIG_FILE" "$PERM_CONFIG" 2>/dev/null || true

if [ -f "$PERM_CONFIG" ]; then
    log "SSO configuration saved to: $PERM_CONFIG"
fi

success "Jellyfin SSO setup complete"
