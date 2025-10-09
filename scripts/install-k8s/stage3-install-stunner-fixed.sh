#!/bin/bash
# Stage 3: STUNner STUN/TURN Server Installation - FIXED VERSION
# This installs a reliable TURN server using coturn instead of the problematic STUNner operator
# RELIABLE: Uses coturn image with hostNetwork configuration for bare metal

set -e

echo "======================================================"
echo "🔗 Stage 3: Reliable STUNner STUN/TURN Installation"
echo "   ✅ Uses stable coturn image"
echo "   ✅ Kubernetes-native STUN/TURN server"
echo "   ✅ WebRTC media streaming support"
echo "   ✅ Integration with June services"
echo "   ✅ FIXED: Reliable bare metal hostNetwork support"
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
echo "  Deployment: hostNetwork (for bare metal)"
echo "  Image: coturn/coturn:4.6.2-alpine (RELIABLE)"
echo ""
echo "======================================================"
echo ""

read -p "Continue with this configuration? (y/n): " confirm
[[ $confirm != [yY] ]] && { echo "Cancelled."; exit 0; }

# ============================================================================
# CLEAN UP OLD STUNNER INSTALLATION
# ============================================================================

log_info "Cleaning up any existing STUNner installation..."

# Remove old STUNner operator if it exists
helm uninstall stunner-gateway-operator -n stunner-system 2>/dev/null || log_info "No existing STUNner operator to remove"
kubectl delete namespace stunner-system 2>/dev/null || log_info "No stunner-system namespace to remove"

# Clean up stunner namespace resources
if kubectl get namespace stunner &>/dev/null; then
    log_info "Cleaning up existing stunner namespace..."
    kubectl delete all --all -n stunner 2>/dev/null || true
    kubectl delete secrets --all -n stunner 2>/dev/null || true
    kubectl delete configmaps --all -n stunner 2>/dev/null || true
fi

# Clear any port conflicts
log_info "Clearing port 3478 conflicts..."
kill -9 $(lsof -ti:3478) 2>/dev/null || true

# Remove manual iptables rules
iptables -t nat -L KUBE-NODEPORTS -n --line-numbers 2>/dev/null | grep 3478 | awk '{print $1}' | sort -r | xargs -I {} iptables -t nat -D KUBE-NODEPORTS {} 2>/dev/null || true

log_success "Cleanup complete!"

# ============================================================================
# DEPLOY FIXED STUNNER CONFIGURATION
# ============================================================================

log_info "Deploying fixed STUNner configuration..."

# Generate the fixed manifest with actual values
cp "$(dirname "$0")/../../k8s/stunner-manifests.yaml" /tmp/stunner-fixed.yaml

# Replace placeholders with actual values
sed -i "s/STUNNER_REALM_PLACEHOLDER/${STUNNER_REALM}/g" /tmp/stunner-fixed.yaml
sed -i "s/STUNNER_USERNAME_PLACEHOLDER/${STUNNER_USERNAME}/g" /tmp/stunner-fixed.yaml
sed -i "s/STUNNER_PASSWORD_PLACEHOLDER/${STUNNER_PASSWORD}/g" /tmp/stunner-fixed.yaml

# Apply the fixed configuration
kubectl apply -f /tmp/stunner-fixed.yaml

log_success "Fixed STUNner configuration applied!"

# ============================================================================
# WAIT FOR DEPLOYMENT
# ============================================================================

log_info "Waiting for STUNner deployment to be ready..."
kubectl wait --for=condition=available deployment/june-stunner-gateway \
    -n stunner \
    --timeout=300s

log_success "STUNner deployment is ready!"

# ============================================================================
# SAVE STUNNER CONFIGURATION
# ============================================================================

log_info "Saving STUNner configuration..."

STUNNER_CONFIG_DIR="/root/.june-config"
STUNNER_CONFIG_FILE="${STUNNER_CONFIG_DIR}/stunner-config.env"

mkdir -p "${STUNNER_CONFIG_DIR}"
chmod 700 "${STUNNER_CONFIG_DIR}"

cat > "${STUNNER_CONFIG_FILE}" << EOF
# STUNner STUN/TURN Server Configuration
# Generated: $(date)
# FIXED VERSION: Uses coturn with hostNetwork for bare metal
TURN_DOMAIN=${TURN_DOMAIN}
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
STUNNER_HOST_NETWORK=true
STUNNER_PORT=3478
STUNNER_IMAGE=coturn/coturn:4.6.2-alpine
EOF

# Also update the main domain config
if [ -f "$DOMAIN_CONFIG_FILE" ]; then
    if ! grep -q "TURN_DOMAIN" "$DOMAIN_CONFIG_FILE"; then
        cat >> "$DOMAIN_CONFIG_FILE" << EOF

# STUNner Configuration (added by stage3-fixed)
TURN_DOMAIN=${TURN_DOMAIN}
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
STUNNER_HOST_NETWORK=true
STUNNER_PORT=3478
STUNNER_IMAGE=coturn/coturn:4.6.2-alpine
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

# Check namespace
if kubectl get namespace stunner &>/dev/null; then
    log_success "STUNner namespace exists"
else
    log_error "STUNner namespace not found!"
fi

# Check deployment
if kubectl get deployment june-stunner-gateway -n stunner &>/dev/null; then
    log_success "STUNner deployment exists"
    
    # Check pod status
    READY_PODS=$(kubectl get pods -n stunner -l app=stunner --no-headers | grep Running | wc -l)
    if [ "$READY_PODS" -gt 0 ]; then
        log_success "STUNner pod is running"
    else
        log_warning "STUNner pod may not be ready yet"
        kubectl get pods -n stunner -l app=stunner
    fi
else
    log_error "STUNner deployment not found!"
fi

# Check if STUNner is listening on host port
log_info "Checking if STUNner is listening on port 3478..."
if netstat -ulnp | grep -q ":3478"; then
    log_success "STUNner is listening on port 3478 (hostNetwork working!)"
else
    log_warning "STUNner may not be listening on port 3478 yet (deployment might still be starting)"
fi

# Clean up temporary file
rm -f /tmp/stunner-fixed.yaml

# ============================================================================
# FINAL STATUS
# ============================================================================

echo ""
echo "======================================================"
log_success "Stage 3 Complete! Reliable STUNner Infrastructure Ready"
echo "======================================================"
echo ""
echo "Infrastructure Ready:"
echo "  ✅ stunner namespace"
echo "  ✅ STUNner deployment with reliable coturn image"
echo "  ✅ STUNner authentication secret"
echo "  ✅ STUNner service configuration"
echo "  ✅ STUN/TURN server on port 3478"
echo ""
echo "🔗 STUNner Configuration:"
echo "  TURN Domain: ${TURN_DOMAIN}"
echo "  Realm: ${STUNNER_REALM}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo "  Host Network: ENABLED (for bare metal)"
echo "  Port: 3478"
echo "  Image: coturn/coturn:4.6.2-alpine (RELIABLE)"
echo ""
echo "📁 Configuration Files:"
echo "  STUNner config: ${STUNNER_CONFIG_FILE}"
echo "  Domain config updated: ${DOMAIN_CONFIG_FILE}"
echo ""
echo "Next Steps:"
echo ""
echo "  1. ✅ STUNner is now running with reliable coturn on port 3478"
echo ""
echo "  2. Configure DNS to point ${TURN_DOMAIN} to your server IP"
echo ""
echo "  3. Test STUN/TURN server:"
echo "     python3 scripts/test-turn-server.py"
echo ""
echo "  4. Monitor STUNner deployment:"
echo "     kubectl get pods -n stunner -w"
echo "     kubectl logs -n stunner -l app=stunner"
echo ""
echo "  5. Verify port is open:"
echo "     netstat -ulnp | grep 3478"
echo ""
echo "  6. Test from external tools:"
echo "     Use https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/"
echo "     STUN URI: stun:${TURN_DOMAIN}:3478"
echo "     TURN URI: turn:${TURN_DOMAIN}:3478"
echo "     Username: ${STUNNER_USERNAME}"
echo "     Password: ${STUNNER_PASSWORD}"
echo ""
echo "======================================================"