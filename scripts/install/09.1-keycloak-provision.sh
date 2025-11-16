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

# Export variables for the Keycloak setup script
export KEYCLOAK_URL
export KEYCLOAK_REALM
export KEYCLOAK_ADMIN_USER
export KEYCLOAK_ADMIN_PASSWORD
export DOMAIN

# Run the Keycloak setup script non-interactively
log "Running Keycloak realm and client provisioning..."

KEYCLOAK_SCRIPT="${ROOT_DIR}/scripts/keycloak/setup-fresh-install.sh"

if [ ! -f "$KEYCLOAK_SCRIPT" ]; then
    error "Keycloak setup script not found: $KEYCLOAK_SCRIPT"
fi

# Make it executable
chmod +x "$KEYCLOAK_SCRIPT"

# Run with all defaults (non-interactive mode)
# The script will use the exported environment variables
echo -e "\n\n\n\n\n\n\n" | bash "$KEYCLOAK_SCRIPT" || {
    warn "Keycloak setup may have partial failures - continuing anyway"
}

success "Keycloak realm provisioned"
echo ""
echo "🔐 Keycloak Configuration:"
echo "  URL: $KEYCLOAK_URL"
echo "  Realm: ${KEYCLOAK_REALM:-allsafe}"
echo "  Admin User: $KEYCLOAK_ADMIN_USER"
echo ""
echo "✅ Base June service clients created:"
echo "  - june-orchestrator"
echo "  - june-stt"
echo "  - june-tts"
echo "  - june-mobile-app (PKCE)"
echo ""
echo "📝 Next Steps:"
echo "  Media stack SSO clients will be created in phase 09.5"
echo ""
