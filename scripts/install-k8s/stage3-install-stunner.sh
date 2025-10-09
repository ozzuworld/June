#!/bin/bash
# Stage 3: STUNner STUN/TURN Server Installation
# This installs STUNner for WebRTC media streaming support

set -e

echo "======================================================"
echo "🔗 Stage 3: STUNner STUN/TURN Server Installation"
echo "   ✅ Kubernetes-native STUN/TURN server"
echo "   ✅ WebRTC media streaming support"
echo "   ✅ Integration with June services"
echo "======================================================"

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

# Configuration
prompt() {
    local prompt_text="$1"
    local var_name="$2"
    local default="$3"
    
    if [ -n "$default" ]; then
        read -p "$prompt_text [$default]: " input
        eval "$var_name=\${input:-$default}"
    else
        read -p "$prompt_text: " input
        eval "$var_name=\$input"
    fi
}

echo ""
log_info "🔗 STUNner Configuration"
echo ""

# Load existing domain config if available
DOMAIN_CONFIG_FILE="/root/.june-config/domain-config.env"
if [ -f "$DOMAIN_CONFIG_FILE" ]; then
    source "$DOMAIN_CONFIG_FILE"
    log_success "Using existing domain configuration: $PRIMARY_DOMAIN"
    TURN_DOMAIN="turn.${PRIMARY_DOMAIN}"
else
    log_warning "No domain configuration found"
    prompt "Primary domain (e.g., example.com)" PRIMARY_DOMAIN "allsafe.world"
    TURN_DOMAIN="turn.${PRIMARY_DOMAIN}"
fi

prompt "TURN server subdomain" TURN_SUBDOMAIN "turn"
TURN_DOMAIN="${TURN_SUBDOMAIN}.${PRIMARY_DOMAIN}"

prompt "STUNner realm" STUNNER_REALM "${TURN_DOMAIN}"
prompt "STUNner username" STUNNER_USERNAME "june-user"
prompt "STUNner password" STUNNER_PASSWORD "Pokemon123!"

echo ""
echo "======================================================"
echo "📋 STUNner Configuration Summary"
echo "======================================================"
echo ""
echo "🌐 Domain Configuration:"
echo "  Primary Domain: ${PRIMARY_DOMAIN}"
echo "  TURN Domain: ${TURN_DOMAIN}"
echo ""
echo "🔗 STUNner Configuration:"
echo "  Realm: ${STUNNER_REALM}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo ""
echo "======================================================"
echo ""

read -p "Continue with this configuration? (y/n): " confirm
[[ $confirm != [yY] ]] && { echo "Cancelled."; exit 0; }

# ============================================================================
# HELM INSTALLATION (if not already installed)
# ============================================================================

log_info "Checking Helm installation..."
if ! command -v helm &> /dev/null; then
    log_info "Installing Helm..."
    cd /tmp
    wget https://get.helm.sh/helm-v3.14.0-linux-amd64.tar.gz
    tar -zxvf helm-v3.14.0-linux-amd64.tar.gz
    mv linux-amd64/helm /usr/local/bin/helm
    chmod +x /usr/local/bin/helm
    rm -rf linux-amd64 helm-v3.14.0-linux-amd64.tar.gz
    log_success "Helm installed"
else
    log_success "Helm already installed"
fi

# ============================================================================
# STUNNER OPERATOR INSTALLATION
# ============================================================================

log_info "Installing STUNner Gateway Operator..."

# Add STUNner Helm repository
helm repo add stunner https://l7mp.io/stunner
helm repo update

# Create stunner-system namespace
kubectl create namespace stunner-system || log_warning "stunner-system namespace already exists"

# Install STUNner Gateway Operator
log_info "Installing STUNner Gateway Operator (this may take a few minutes)..."
helm install stunner-gateway-operator stunner/stunner-gateway-operator \
    --create-namespace \
    --namespace=stunner-system \
    --wait \
    --timeout=10m || {
    log_error "Failed to install STUNner Gateway Operator"
    exit 1
}

log_success "STUNner Gateway Operator installed!"

# Wait for operator to be ready
log_info "Waiting for STUNner operator to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=stunner-gateway-operator \
    -n stunner-system \
    --timeout=300s

log_success "STUNner operator is ready!"

# ============================================================================
# STUNNER NAMESPACE AND CONFIGURATION
# ============================================================================

log_info "Creating STUNner namespace and configuration..."

# Create stunner namespace for June services
kubectl create namespace stunner || log_warning "stunner namespace already exists"

# Create STUNner authentication secret
kubectl create secret generic stunner-auth-secret \
    --from-literal=type=static \
    --from-literal=username="$STUNNER_USERNAME" \
    --from-literal=password="$STUNNER_PASSWORD" \
    --namespace=stunner \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "STUNner authentication secret created!"

# ============================================================================
# SAVE STUNNER CONFIGURATION
# ============================================================================

log_info "Saving STUNner configuration..."

STUNNER_CONFIG_DIR="/root/.june-config"
STUNNER_CONFIG_FILE="${STUNNER_CONFIG_DIR}/stunner-config.env"

mkdir -p "${STUNNER_CONFIG_DIR}"
chmod 700 "${STUNNER_CONFIG_DIR}"

cat >> "${STUNNER_CONFIG_FILE}" << EOF

# STUNner STUN/TURN Server Configuration
# Generated: $(date)
TURN_DOMAIN=${TURN_DOMAIN}
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
EOF

# Also update the main domain config
if [ -f "$DOMAIN_CONFIG_FILE" ]; then
    if ! grep -q "TURN_DOMAIN" "$DOMAIN_CONFIG_FILE"; then
        cat >> "$DOMAIN_CONFIG_FILE" << EOF

# STUNner Configuration (added by stage3)
TURN_DOMAIN=${TURN_DOMAIN}
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
EOF
    fi
fi

chmod 600 "${STUNNER_CONFIG_FILE}"
log_success "STUNner configuration saved to: ${STUNNER_CONFIG_FILE}"

# ============================================================================
# POST-INSTALL VERIFICATION
# ============================================================================

echo ""
echo "======================================================"
log_info "Running Post-Install Verification..."
echo "======================================================"
echo ""

# Check STUNner operator
log_info "Checking STUNner operator..."
if kubectl get pods -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator | grep -q Running; then
    log_success "STUNner operator is running"
else
    log_error "STUNner operator not running!"
fi

# Check namespace
if kubectl get namespace stunner &>/dev/null; then
    log_success "STUNner namespace exists"
else
    log_error "STUNner namespace not found!"
fi

# Check secret
if kubectl get secret stunner-auth-secret -n stunner &>/dev/null; then
    log_success "STUNner authentication secret exists"
else
    log_error "STUNner authentication secret not found!"
fi

# ============================================================================
# FINAL STATUS
# ============================================================================

echo ""
echo "======================================================"
log_success "Stage 3 Complete! STUNner Infrastructure Ready"
echo "======================================================"
echo ""
echo "Infrastructure Ready:"
echo "  ✅ STUNner Gateway Operator"
echo "  ✅ stunner-system namespace"
echo "  ✅ stunner namespace"
echo "  ✅ STUNner authentication secret"
echo ""
echo "🔗 STUNner Configuration:"
echo "  TURN Domain: ${TURN_DOMAIN}"
echo "  Realm: ${STUNNER_REALM}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo ""
echo "📁 Configuration Files:"
echo "  STUNner config: ${STUNNER_CONFIG_FILE}"
echo "  Domain config updated: ${DOMAIN_CONFIG_FILE}"
echo ""
echo "Next Steps:"
echo ""
echo "  1. Configure DNS to point ${TURN_DOMAIN} to your server IP"
echo ""
echo "  2. Push to GitHub to trigger automated deployment"
echo "     (STUNner resources will be deployed automatically)"
echo ""
echo "  3. Monitor STUNner deployment:"
echo "     kubectl get pods -n stunner -w"
echo ""
echo "  4. Test STUN/TURN server:"
echo "     Use https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/"
echo "     STUN URI: stun:${TURN_DOMAIN}:3478"
echo "     TURN URI: turn:${TURN_DOMAIN}:3478"
echo "     Username: ${STUNNER_USERNAME}"
echo "     Password: ${STUNNER_PASSWORD}"
echo ""
echo "======================================================"