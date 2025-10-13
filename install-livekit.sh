#!/bin/bash
# June Platform - LiveKit + STUNner Installation Script
# Replaces the old Janus WebRTC implementation with LiveKit

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "=========================================="
echo "June Platform - LiveKit + STUNner Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install-livekit.sh)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration file
CONFIG_FILE="${SCRIPT_DIR}/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE"
fi

log "Loading configuration from: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
REQUIRED_VARS=(
    "DOMAIN"
    "LETSENCRYPT_EMAIL"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        error "Required variable $var is not set in $CONFIG_FILE"
    fi
done

success "Configuration loaded"
log "Domain: $DOMAIN"

# ============================================================================
# STEP 1: Install Prerequisites (Helm, kubectl, etc.)
# ============================================================================

install_prerequisites() {
    log "Installing prerequisites..."
    
    # Install Helm if not present
    if ! command -v helm &> /dev/null; then
        log "Installing Helm..."
        curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
        success "Helm installed"
    else
        success "Helm already installed"
    fi
    
    # Verify kubectl
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster not available. Please run the main install.sh first."
    fi
    
    success "Prerequisites ready"
}

# ============================================================================
# STEP 2: Install STUNner (if not already installed)
# ============================================================================

install_stunner() {
    log "Setting up STUNner..."
    
    # Check if STUNner is already installed
    if helm list -n stunner-system 2>/dev/null | grep -q stunner; then
        success "STUNner already installed"
    else
        log "Installing STUNner..."
        
        # Install Gateway API
        kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml > /dev/null 2>&1
        sleep 10
        
        # Add STUNner repo and install
        helm repo add stunner https://l7mp.io/stunner > /dev/null 2>&1
        helm repo update > /dev/null 2>&1
        
        helm install stunner stunner/stunner \
            --create-namespace \
            --namespace=stunner-system \
            --wait \
            --timeout=10m > /dev/null 2>&1
        
        success "STUNner installed"
    fi
    
    # Apply STUNner configuration from k8s/stunner/
    log "Applying STUNner configuration..."
    
    # Replace DOMAIN placeholder in secret template
    sed "s/{{DOMAIN}}/${DOMAIN}/g" "${SCRIPT_DIR}/k8s/stunner/10-secret.template.yaml" > "/tmp/stunner-secret.yaml"
    
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/00-namespaces.yaml" > /dev/null 2>&1
    kubectl apply -f "/tmp/stunner-secret.yaml" > /dev/null 2>&1
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/20-dataplane-hostnet.yaml" > /dev/null 2>&1
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/30-gatewayconfig.yaml" > /dev/null 2>&1
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/40-gatewayclass.yaml" > /dev/null 2>&1
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/50-gateway.yaml" > /dev/null 2>&1
    
    rm -f "/tmp/stunner-secret.yaml"
    
    success "STUNner configured"
}

# ============================================================================
# STEP 3: Install LiveKit
# ============================================================================

install_livekit() {
    log "Installing LiveKit..."
    
    # Create media namespace
    kubectl create namespace media --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Add LiveKit Helm repo
    if ! helm repo list 2>/dev/null | grep -q livekit; then
        log "Adding LiveKit Helm repository..."
        helm repo add livekit https://helm.livekit.io > /dev/null 2>&1
        helm repo update > /dev/null 2>&1
    fi
    
    # Install/upgrade LiveKit
    log "Deploying LiveKit server..."
    helm upgrade --install livekit livekit/livekit-server \
        --namespace media \
        --values "${SCRIPT_DIR}/k8s/livekit/livekit-values.yaml" \
        --wait \
        --timeout=10m > /dev/null 2>&1
    
    # Apply additional UDP service
    kubectl apply -f "${SCRIPT_DIR}/k8s/livekit/livekit-udp-svc.yaml" > /dev/null 2>&1
    
    success "LiveKit installed"
}

# ============================================================================
# STEP 4: Configure UDPRoute for LiveKit
# ============================================================================

configure_udp_route() {
    log "Configuring STUNner UDPRoute for LiveKit..."
    
    # Wait for LiveKit service to be ready
    log "Waiting for LiveKit service..."
    for i in {1..30}; do
        if kubectl get svc -n media livekit-udp &>/dev/null; then
            success "LiveKit service ready"
            break
        fi
        sleep 5
    done
    
    # Apply UDPRoute
    kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/60-udproute-livekit.yaml" > /dev/null 2>&1
    
    success "UDPRoute configured"
}

# ============================================================================
# STEP 5: Remove Old Janus Components (if they exist)
# ============================================================================

cleanup_janus() {
    log "Cleaning up old Janus components..."
    
    # Remove Janus deployment and service if they exist
    kubectl delete deployment june-janus -n june-services &>/dev/null || true
    kubectl delete service june-janus -n june-services &>/dev/null || true
    
    # Remove any Janus-related UDPRoutes
    kubectl delete udproute june-janus-route -n stunner &>/dev/null || true
    
    # Remove old janus ingress if it exists
    kubectl delete ingress june-janus -n june-services &>/dev/null || true
    
    success "Janus cleanup complete"
}

# ============================================================================
# STEP 6: Verify Installation
# ============================================================================

verify_installation() {
    log "Verifying installation..."
    
    # Check STUNner gateway
    if kubectl get gateway -n stunner stunner-gateway &>/dev/null; then
        success "STUNner gateway ready"
    else
        warn "STUNner gateway not found"
    fi
    
    # Check LiveKit
    if kubectl get deployment -n media livekit &>/dev/null; then
        success "LiveKit deployment ready"
    else
        warn "LiveKit deployment not found"
    fi
    
    # Check UDPRoute
    if kubectl get udproute -n stunner livekit-udp-route &>/dev/null; then
        success "UDPRoute configured"
    else
        warn "UDPRoute not found"
    fi
    
    # Get STUNner external endpoint
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    success "LiveKit + STUNner Installation Complete!"
    echo "=========================================="
    echo ""
    echo "🎯 STUNner TURN Server:"
    echo "  URL:        turn:${EXTERNAL_IP}:3478"
    echo "  Username:   june-user"
    echo "  Password:   Pokemon123!"
    echo ""
    echo "🎮 LiveKit Server:"
    echo "  Internal:   livekit.media.svc.cluster.local"
    echo "  API Port:   80"
    echo "  RTP Port:   7882"
    echo ""
    echo "📊 Check Status:"
    echo "  kubectl get pods -n media"
    echo "  kubectl get gateway -n stunner"
    echo "  kubectl get udproute -n stunner"
    echo ""
    echo "🧪 Test STUNner:"
    echo "  ./test-stunner.sh"
    echo ""
    echo "=========================================="
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    install_prerequisites
    install_stunner
    install_livekit
    configure_udp_route
    cleanup_janus
    verify_installation
}

main "$@"