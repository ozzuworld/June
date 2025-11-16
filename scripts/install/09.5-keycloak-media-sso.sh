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

AUTOMATION_DIR="${ROOT_DIR}/scripts/automation-media-stack"

log "Setting up Media Stack SSO for domain: $DOMAIN"
echo ""
echo "🔐 Keycloak Media Stack SSO Setup"
echo "=================================="
echo "  Domain: $DOMAIN"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Realm: ${KEYCLOAK_REALM:-allsafe}"
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

# Step 2: Get Jellyfin API key
log "Step 2: Getting Jellyfin API key..."
echo ""

# Check if we have API key already
if [ -z "$JELLYFIN_API_KEY" ]; then
    warn "JELLYFIN_API_KEY not set in config.env"
    log "You'll need to get the API key manually:"
    echo "  1. Login to Jellyfin as admin"
    echo "  2. Dashboard > API Keys > Create new API key"
    echo "  3. Add to config.env: JELLYFIN_API_KEY=your-key-here"
    echo ""
    read -p "Enter Jellyfin API key now (or press Enter to skip SSO plugin installation): " MANUAL_API_KEY

    if [ -n "$MANUAL_API_KEY" ]; then
        JELLYFIN_API_KEY="$MANUAL_API_KEY"
    else
        warn "Skipping Jellyfin SSO plugin installation - set JELLYFIN_API_KEY and run manually"
        SKIP_JELLYFIN_SSO=true
    fi
fi

# Step 3: Install Jellyfin SSO plugin
if [ "$SKIP_JELLYFIN_SSO" != "true" ]; then
    log "Step 3: Jellyfin SSO plugin setup..."
    echo ""

    warn "Jellyfin SSO plugin requires manual installation"
    echo ""
    echo "📝 Manual Jellyfin SSO Plugin Setup:"
    echo ""
    echo "1. Login to Jellyfin: https://tv.${DOMAIN}"
    echo "   Username: ${JELLYFIN_USERNAME}"
    echo "   Password: ${JELLYFIN_PASSWORD}"
    echo ""
    echo "2. Go to: Dashboard > Plugins > Repositories"
    echo ""
    echo "3. Click '+' and add repository:"
    echo "   https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json"
    echo ""
    echo "4. Go to: Dashboard > Plugins > Catalog"
    echo ""
    echo "5. Find 'SSO-Auth' plugin and click Install"
    echo ""
    echo "6. Restart Jellyfin when prompted"
    echo ""
    echo "7. After restart, go to: Dashboard > Plugins > SSO-Auth"
    echo ""
    echo "8. Configure OIDC Provider 'keycloak':"
    echo "   - OID Endpoint: ${KEYCLOAK_URL}/realms/${REALM}"
    echo "   - Client ID: jellyfin"
    echo "   - Client Secret: ${JELLYFIN_CLIENT_SECRET}"
    echo "   - Enabled: ✓"
    echo "   - Enable Authorization: ✓"
    echo "   - Enable All Folders: ✓"
    echo "   - Admin Roles: jellyfin-admin"
    echo "   - Roles: jellyfin-user"
    echo "   - Role Claim: realm_access.roles"
    echo ""
    echo "9. Save settings"
    echo ""
    warn "Complete these steps before proceeding to assign users roles in Keycloak"
    echo ""
fi

# Step 5: Configure Jellyseerr OIDC
log "Step 5: Jellyseerr OIDC setup..."
echo ""

warn "Jellyseerr OIDC configuration requires manual setup"
echo ""
echo "📝 Manual Jellyseerr OIDC Setup:"
echo ""
echo "1. Login to Jellyseerr: https://requests.${DOMAIN}"
echo "   Email: mail@${DOMAIN}"
echo "   Password: ${JELLYFIN_PASSWORD}"
echo ""
echo "2. Go to: Settings > General"
echo ""
echo "3. Scroll to 'Authentication' section"
echo ""
echo "4. Enable 'Enable OIDC Sign-In'"
echo ""
echo "5. Configure OIDC settings:"
echo "   - OIDC Issuer URL: ${KEYCLOAK_URL}/realms/${REALM}"
echo "   - OIDC Client ID: jellyseerr"
echo "   - OIDC Client Secret: ${JELLYSEERR_CLIENT_SECRET}"
echo "   - Button Text: Sign in with Keycloak"
echo ""
echo "6. Save settings"
echo ""
warn "Note: Jellyseerr preview-OIDC build may have different UI - check Settings > Authentication"
echo ""

# Summary
echo ""
echo "═══════════════════════════════════════════════"
success "Media Stack SSO Configuration Complete!"
echo "═══════════════════════════════════════════════"
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
echo "🔑 Keycloak Role Management:"
echo "  Admin Portal: ${KEYCLOAK_URL}/admin"
echo ""
echo "  Jellyfin Roles:"
echo "    - jellyfin-admin (administrators)"
echo "    - jellyfin-user (regular users)"
echo ""
echo "  Jellyseerr Roles:"
echo "    - jellyseerr-admin (administrators)"
echo "    - jellyseerr-user (regular users)"
echo ""
echo "📝 Next Steps:"
echo "  1. Login to Keycloak: ${KEYCLOAK_URL}/admin"
echo "  2. Navigate to Realm: $REALM > Users"
echo "  3. Assign roles to users for access control"
echo "  4. Test SSO login on both services"
echo ""
echo "🧪 Testing:"
echo "  Jellyfin: Visit https://tv.${DOMAIN} and click SSO button"
echo "  Jellyseerr: Visit https://requests.${DOMAIN} and click Keycloak button"
echo ""
echo "💡 Custom Frontend Integration:"
echo "  Your mobile app can use the same Keycloak realm"
echo "  Use the 'june-mobile-app' client (if configured)"
echo "  Exchange Keycloak tokens for service-specific sessions"
echo ""
echo "📄 Configuration saved to: $SSO_CONFIG_FILE"
echo "═══════════════════════════════════════════════"
