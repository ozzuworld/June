#!/bin/bash
# Template Processing Script for June Manifests
# Processes template placeholders with actual configuration values
# Usage: ./scripts/generate-manifests.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

echo "======================================================"
echo "📝 June Manifest Template Processing"
echo "======================================================"

# Configuration
CONFIG_DIR="/root/.june-config"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_FILE="$REPO_ROOT/k8s/complete-manifests.yaml"
OUTPUT_FILE="$REPO_ROOT/k8s/complete-manifests-processed.yaml"

# Check if template exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    log_error "Template file not found: $TEMPLATE_FILE"
    exit 1
fi

# Load configuration files
if [ ! -f "$CONFIG_DIR/domain-config.env" ]; then
    log_error "Domain configuration not found! Run install-june-platform.sh first."
    exit 1
fi

log_info "Loading configuration..."
source "$CONFIG_DIR/domain-config.env"

# Load infrastructure config if available
if [ -f "$CONFIG_DIR/infrastructure.env" ]; then
    source "$CONFIG_DIR/infrastructure.env"
fi

# Load networking config if available
if [ -f "$CONFIG_DIR/networking.env" ]; then
    source "$CONFIG_DIR/networking.env"
fi

# Set defaults for missing values
KEYCLOAK_REALM=${KEYCLOAK_REALM:-"june-realm"}

# Display configuration summary
log_info "Configuration Summary:"
echo "  Primary Domain: $PRIMARY_DOMAIN"
echo "  API Domain: $API_DOMAIN"
echo "  IDP Domain: $IDP_DOMAIN"
echo "  STT Domain: $STT_DOMAIN"
echo "  TTS Domain: $TTS_DOMAIN"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo "  Keycloak Realm: $KEYCLOAK_REALM"
if [ -n "$TURN_DOMAIN" ]; then
    echo "  TURN Domain: $TURN_DOMAIN"
fi

# Create processed manifest
log_info "Processing manifest template..."

sed -e "s/{{PRIMARY_DOMAIN}}/$PRIMARY_DOMAIN/g" \
    -e "s/{{API_DOMAIN}}/$API_DOMAIN/g" \
    -e "s/{{IDP_DOMAIN}}/$IDP_DOMAIN/g" \
    -e "s/{{STT_DOMAIN}}/$STT_DOMAIN/g" \
    -e "s/{{TTS_DOMAIN}}/$TTS_DOMAIN/g" \
    -e "s/{{WILDCARD_DOMAIN}}/$WILDCARD_DOMAIN/g" \
    -e "s/{{CERT_SECRET_NAME}}/$CERT_SECRET_NAME/g" \
    -e "s/{{KEYCLOAK_REALM}}/$KEYCLOAK_REALM/g" \
    "$TEMPLATE_FILE" > "$OUTPUT_FILE"

# Update TURN domain in WebRTC config if available
if [ -n "$TURN_DOMAIN" ]; then
    log_info "Updating TURN domain to: $TURN_DOMAIN"
    sed -i "s/turn\.{{PRIMARY_DOMAIN}}/turn.$PRIMARY_DOMAIN/g" "$OUTPUT_FILE"
    sed -i "s/stun\.{{PRIMARY_DOMAIN}}/stun.$PRIMARY_DOMAIN/g" "$OUTPUT_FILE"
else
    log_warning "TURN domain not configured, using primary domain"
    sed -i "s/turn\.{{PRIMARY_DOMAIN}}/turn.$PRIMARY_DOMAIN/g" "$OUTPUT_FILE"
    sed -i "s/stun\.{{PRIMARY_DOMAIN}}/stun.$PRIMARY_DOMAIN/g" "$OUTPUT_FILE"
fi

# Validate output
if [ ! -f "$OUTPUT_FILE" ]; then
    log_error "Failed to create processed manifest!"
    exit 1
fi

# Check for remaining placeholders
REMAINING_PLACEHOLDERS=$(grep -o "{{[^}]*}}" "$OUTPUT_FILE" 2>/dev/null || true)
if [ -n "$REMAINING_PLACEHOLDERS" ]; then
    log_warning "Remaining unprocessed placeholders found:"
    echo "$REMAINING_PLACEHOLDERS" | sort -u
    echo ""
    log_warning "You may need to update these manually or add them to configuration"
fi

# Display file info
TEMPLATE_SIZE=$(wc -l < "$TEMPLATE_FILE")
OUTPUT_SIZE=$(wc -l < "$OUTPUT_FILE")

log_success "Manifest processing complete!"
echo ""
echo "📄 Files:"
echo "  Template: $TEMPLATE_FILE ($TEMPLATE_SIZE lines)"
echo "  Processed: $OUTPUT_FILE ($OUTPUT_SIZE lines)"
echo ""
echo "🚀 Ready for deployment:"
echo "  kubectl apply -f $OUTPUT_FILE"
echo ""