#!/bin/bash
# Manifest Generator Script for June Platform
# Generates final manifests from template using domain configuration
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

CONFIG_DIR="/root/.june-config"
TEMPLATE_FILE="k8s/complete-manifests.template.yaml"
OUTPUT_FILE="k8s/complete-manifests.yaml"

echo "======================================================"
log_info "🔧 June Platform Manifest Generator"
echo "======================================================"
echo ""

# Check if running from correct directory
if [ ! -f "$TEMPLATE_FILE" ]; then
    log_error "Template file not found: $TEMPLATE_FILE"
    log_error "Please run this script from the project root directory"
    exit 1
fi

# Load domain configuration
if [ ! -f "$CONFIG_DIR/domain-config.env" ]; then
    log_error "Domain configuration not found: $CONFIG_DIR/domain-config.env"
    log_error "Please run install-core-infrastructure.sh first"
    exit 1
fi

log_info "Loading domain configuration..."
source "$CONFIG_DIR/domain-config.env"

# Validate required variables
REQUIRED_VARS=(
    "PRIMARY_DOMAIN"
    "API_DOMAIN" 
    "IDP_DOMAIN"
    "STT_DOMAIN"
    "TTS_DOMAIN"
    "WILDCARD_DOMAIN"
    "CERT_SECRET_NAME"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        log_error "Required variable $var is not set in domain configuration"
        exit 1
    fi
done

# Generate Keycloak realm name from domain
KEYCLOAK_REALM="${PRIMARY_DOMAIN%%.*}"  # Extract first part of domain (e.g., "allsafe" from "allsafe.world")

log_info "🔧 Configuration Summary:"
echo "  Primary Domain: $PRIMARY_DOMAIN"
echo "  API Domain: $API_DOMAIN"
echo "  IDP Domain: $IDP_DOMAIN"
echo "  STT Domain: $STT_DOMAIN"
echo "  TTS Domain: $TTS_DOMAIN"
echo "  Wildcard Domain: $WILDCARD_DOMAIN"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo "  Keycloak Realm: $KEYCLOAK_REALM"
echo ""

log_info "📝 Generating manifests from template..."

# Create backup of existing manifest if it exists
if [ -f "$OUTPUT_FILE" ]; then
    BACKUP_FILE="${OUTPUT_FILE}.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$OUTPUT_FILE" "$BACKUP_FILE"
    log_info "Backed up existing manifest to: $BACKUP_FILE"
fi

# Process template and generate final manifest
cat "$TEMPLATE_FILE" | \
    sed "s/{{PRIMARY_DOMAIN}}/$PRIMARY_DOMAIN/g" | \
    sed "s/{{API_DOMAIN}}/$API_DOMAIN/g" | \
    sed "s/{{IDP_DOMAIN}}/$IDP_DOMAIN/g" | \
    sed "s/{{STT_DOMAIN}}/$STT_DOMAIN/g" | \
    sed "s/{{TTS_DOMAIN}}/$TTS_DOMAIN/g" | \
    sed "s/{{WILDCARD_DOMAIN}}/$WILDCARD_DOMAIN/g" | \
    sed "s/{{CERT_SECRET_NAME}}/$CERT_SECRET_NAME/g" | \
    sed "s/{{KEYCLOAK_REALM}}/$KEYCLOAK_REALM/g" \
    > "$OUTPUT_FILE"

if [ $? -eq 0 ]; then
    log_success "✅ Manifests generated successfully!"
    log_info "📄 Output file: $OUTPUT_FILE"
    
    # Validate the generated YAML
    if command -v kubectl >/dev/null 2>&1; then
        log_info "🔍 Validating generated manifests..."
        if kubectl apply --dry-run=client -f "$OUTPUT_FILE" >/dev/null 2>&1; then
            log_success "✅ Manifest validation passed"
        else
            log_warning "⚠️  Manifest validation failed - please check syntax"
            kubectl apply --dry-run=client -f "$OUTPUT_FILE" 2>&1 | tail -10
        fi
    fi
    
    echo ""
    log_info "📋 Generated Configuration:"
    echo "  🌐 API Endpoint: https://$API_DOMAIN"
    echo "  🔐 Identity Provider: https://$IDP_DOMAIN"
    echo "  🎤 Speech-to-Text: https://$STT_DOMAIN"
    echo "  🔊 Text-to-Speech: https://$TTS_DOMAIN"
    echo "  📜 Certificate: $CERT_SECRET_NAME"
    echo ""
    
    log_info "📝 Next Steps:"
    echo "  kubectl apply -f $OUTPUT_FILE"
    echo ""
    
else
    log_error "❌ Failed to generate manifests"
    exit 1
fi

log_success "🎉 Manifest generation complete!"
echo "======================================================"
