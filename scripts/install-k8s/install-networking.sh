#!/bin/bash
# Networking Setup: MetalLB + STUNner with Gateway API v1alpha2
# Run this after install-core-infrastructure.sh
# Usage: ./install-networking.sh

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
echo "🌐 Networking Setup: MetalLB + STUNner"
echo "   Gateway API v1alpha2 with WebRTC Support"
echo "======================================================"
echo ""

# Configuration
CONFIG_DIR="/root/.june-config"
mkdir -p "$CONFIG_DIR"

# Check prerequisites
if ! kubectl cluster-info &>/dev/null; then
    log_error "Kubernetes not running! Run install-core-infrastructure.sh first"
    exit 1
fi

# Load or collect configuration
if [ -f "$CONFIG_DIR/networking.env" ]; then
    log_info "Loading existing networking configuration..."
    source "$CONFIG_DIR/networking.env"
else
    log_info "Collecting networking configuration..."
    
    # Detect external IP
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || curl -s http://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo "Detected external IP: $EXTERNAL_IP"
    read -p "Confirm external IP [$EXTERNAL_IP]: " IP_INPUT
    EXTERNAL_IP=${IP_INPUT:-$EXTERNAL_IP}
    
    # TURN domain
    read -p "TURN domain [turn.ozzu.world]: " TURN_DOMAIN
    TURN_DOMAIN=${TURN_DOMAIN:-turn.ozzu.world}
    
    # TURN credentials
    read -p "TURN username [june-user]: " TURN_USERNAME
    TURN_USERNAME=${TURN_USERNAME:-june-user}
    
    read -p "TURN password [Pokemon123!]: " TURN_PASSWORD
    TURN_PASSWORD=${TURN_PASSWORD:-Pokemon123!}
    
    # Save configuration
cat > "$CONFIG_DIR/networking.env" << EOF
EXTERNAL_IP=$EXTERNAL_IP
TURN_DOMAIN=$TURN_DOMAIN
TURN_USERNAME=$TURN_USERNAME
TURN_PASSWORD=$TURN_PASSWORD
INSTALL_DATE="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
EOF
    chmod 600 "$CONFIG_DIR/networking.env"
fi

echo ""
log_info "Configuration:"
echo "  External IP: $EXTERNAL_IP"
echo "  TURN Domain: $TURN_DOMAIN"
echo "  TURN Username: $TURN_USERNAME"
echo "  TURN Password: ${TURN_PASSWORD:0:3}***"
echo ""

# ============================================================================
# METALLB
# ============================================================================

log_info "🌐 Installing MetalLB..."

if kubectl get namespace metallb-system &>/dev/null; then
    log_success "MetalLB already installed"
else
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml
    
    log_info "Waiting for MetalLB controller..."
    kubectl wait --namespace metallb-system \
        --for=condition=ready pod \
        --selector=app=metallb \
        --timeout=180s
    
    sleep 10
    log_success "MetalLB installed!"
fi

# Configure IP pool
log_info "Configuring MetalLB IP pool..."
cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: june-pool
  namespace: metallb-system
spec:
  addresses:
  - ${EXTERNAL_IP}/32
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: june-l2
  namespace: metallb-system
spec:
  ipAddressPools:
  - june-pool
EOF

log_success "MetalLB configured with IP: $EXTERNAL_IP"

# ============================================================================
# GATEWAY API (v1alpha2)
# ============================================================================

log_info "🔗 Installing Gateway API v0.8.0 (v1alpha2)..."

# Install Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v0.8.0/standard-install.yaml

# Wait for CRDs
log_info "Waiting for Gateway API CRDs..."
kubectl wait --for condition=established --timeout=60s \
    crd/gatewayclasses.gateway.networking.k8s.io \
    crd/gateways.gateway.networking.k8s.io \
    crd/httproutes.gateway.networking.k8s.io 2>/dev/null || log_warning "CRDs taking longer"

sleep 5
log_success "Gateway API v1alpha2 installed!"

# ============================================================================
# STUNNER OPERATOR
# ============================================================================

log_info "🎯 Installing STUNner Operator..."

# Create namespaces
kubectl create namespace stunner-system || true
kubectl create namespace stunner || true

# Install Helm if needed
if ! command -v helm &> /dev/null; then
    log_info "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Add STUNner repo
helm repo add stunner https://l7mp.io/stunner
helm repo update

# Install operator
if helm list -n stunner-system | grep -q stunner-gateway-operator; then
    log_success "STUNner operator already installed"
else
    log_info "Installing STUNner operator (this may take 5-10 minutes)..."
    
    # First, try to install without --wait (faster feedback)
    helm install stunner-gateway-operator stunner/stunner-gateway-operator \
        --namespace=stunner-system \
        --set stunnerGatewayOperator.dataplane.spec.replicas=1 \
        --timeout=15m
    
    log_info "Operator installation initiated, waiting for pods..."
    
    # Wait for deployment with better error handling
    TIMEOUT=600  # 10 minutes
    ELAPSED=0
    INTERVAL=10
    
    while [ $ELAPSED -lt $TIMEOUT ]; do
        # Check if deployment exists
        if kubectl get deployment stunner-gateway-operator -n stunner-system &>/dev/null; then
            # Check if deployment is available
            AVAILABLE=$(kubectl get deployment stunner-gateway-operator -n stunner-system -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "0")
            
            if [ "$AVAILABLE" = "1" ]; then
                log_success "STUNner operator is ready!"
                break
            fi
            
            # Show progress
            READY=$(kubectl get deployment stunner-gateway-operator -n stunner-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            echo "  Progress: $READY/1 replicas ready... (${ELAPSED}s elapsed)"
        else
            echo "  Waiting for deployment to be created... (${ELAPSED}s elapsed)"
        fi
        
        sleep $INTERVAL
        ELAPSED=$((ELAPSED + INTERVAL))
    done
    
    if [ $ELAPSED -ge $TIMEOUT ]; then
        log_error "Operator installation timed out after ${TIMEOUT}s"
        echo ""
        echo "Debugging information:"
        echo "====================" 
        kubectl get all -n stunner-system
        echo ""
        echo "Pod details:"
        kubectl describe pods -n stunner-system
        echo ""
        echo "Events:"
        kubectl get events -n stunner-system --sort-by='.lastTimestamp' | tail -20
        exit 1
    fi
fi

# Wait for operator with explicit check
log_info "Verifying operator is fully ready..."
kubectl wait --for=condition=available deployment/stunner-gateway-operator \
    -n stunner-system \
    --timeout=180s 2>/dev/null || {
    log_warning "Wait command had issues, checking manually..."
    
    # Manual check
    AVAILABLE=$(kubectl get deployment stunner-gateway-operator -n stunner-system -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "0")
    if [ "$AVAILABLE" = "1" ]; then
        log_success "Operator verified as ready"
    else
        log_error "Operator not ready. Checking status..."
        kubectl get deployment stunner-gateway-operator -n stunner-system
        kubectl get pods -n stunner-system
        exit 1
    fi
}

# ============================================================================
# STUNNER GATEWAY CONFIGURATION
# ============================================================================

log_info "⚙️  Configuring STUNner Gateway..."

# GatewayConfig
cat <<EOF | kubectl apply -f -
apiVersion: stunner.l7mp.io/v1alpha1
kind: GatewayConfig
metadata:
  name: stunner-gatewayconfig
  namespace: stunner-system
spec:
  realm: ${TURN_DOMAIN}
  authType: static
  userName: ${TURN_USERNAME}
  password: ${TURN_PASSWORD}
  logLevel: all:INFO
EOF

# GatewayClass
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: GatewayClass
metadata:
  name: stunner-gatewayclass
spec:
  controllerName: "stunner.l7mp.io/gateway-operator"
  parametersRef:
    group: stunner.l7mp.io
    kind: GatewayConfig
    name: stunner-gatewayconfig
    namespace: stunner-system
  description: "STUNner Gateway for June WebRTC"
EOF

# Gateway with LoadBalancer
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: Gateway
metadata:
  name: june-stunner-gateway
  namespace: stunner
  annotations:
    stunner.l7mp.io/service-type: LoadBalancer
    stunner.l7mp.io/enable-mixed-protocol-lb: "true"
    metallb.universe.tf/address-pool: june-pool
spec:
  gatewayClassName: stunner-gatewayclass
  listeners:
  - name: udp-listener
    port: 3478
    protocol: UDP
  - name: tcp-listener
    port: 3478
    protocol: TCP
EOF

log_success "STUNner Gateway created!"

# Wait for Gateway
log_info "Waiting for Gateway to be ready (may take 2-3 minutes)..."
kubectl wait --for=condition=Ready gateway/june-stunner-gateway \
    -n stunner \
    --timeout=300s || log_warning "Gateway taking longer than expected"

# ============================================================================
# REFERENCEGRANT FOR CROSS-NAMESPACE ACCESS
# ============================================================================

log_info "🔐 Creating ReferenceGrant for cross-namespace access..."
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: ReferenceGrant
metadata:
  name: stunner-to-june-services
  namespace: june-services
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF

log_success "ReferenceGrant created!"

# ============================================================================
# VERIFICATION
# ============================================================================

log_info "🔍 Verifying installation..."

# Get LoadBalancer IP
sleep 10
STUNNER_SVC=$(kubectl get svc -n stunner -l "stunner.l7mp.io/related-gateway-name=june-stunner-gateway" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -n "$STUNNER_SVC" ]; then
    STUNNER_LB_IP=$(kubectl get svc "$STUNNER_SVC" -n stunner -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
    log_success "LoadBalancer service: $STUNNER_SVC"
    log_success "LoadBalancer IP: $STUNNER_LB_IP"
else
    log_warning "LoadBalancer service not found yet"
fi

# Check dataplane pods
DATAPLANE_PODS=$(kubectl get pods -n stunner -l "stunner.l7mp.io/related-gateway-name=june-stunner-gateway" --no-headers 2>/dev/null | wc -l)
if [ "$DATAPLANE_PODS" -gt 0 ]; then
    log_success "STUNner dataplane running ($DATAPLANE_PODS pod(s))"
else
    log_warning "Dataplane pods not ready yet"
fi

# ============================================================================
# ICE SERVERS CONFIGURATION
# ============================================================================

log_info "📝 Generating ICE servers configuration..."

# Create ICE servers JSON for orchestrator
ICE_SERVERS_JSON=$(cat <<EOF
[
  {
    "urls": ["stun:${TURN_DOMAIN}:3478"]
  },
  {
    "urls": ["turn:${TURN_DOMAIN}:3478"],
    "username": "${TURN_USERNAME}",
    "credential": "${TURN_PASSWORD}"
  }
]
EOF
)

# Save to config
cat > "$CONFIG_DIR/ice-servers.json" << EOF
$ICE_SERVERS_JSON
EOF

log_success "ICE servers configuration saved to $CONFIG_DIR/ice-servers.json"

# ============================================================================
# SUMMARY
# ============================================================================

echo ""
echo "======================================================"
log_success "Networking Setup Complete!"
echo "======================================================"
echo ""
echo "✅ Installed Components:"
echo "  • MetalLB (IP: $EXTERNAL_IP)"
echo "  • Gateway API v1alpha2"
echo "  • STUNner Operator"
echo "  • STUNner Gateway (LoadBalancer)"
echo "  • ReferenceGrant for cross-namespace routing"
echo ""
echo "🔗 STUNner Configuration:"
echo "  Gateway: june-stunner-gateway"
echo "  LoadBalancer IP: ${STUNNER_LB_IP:-pending}"
echo "  STUN URI: stun:${TURN_DOMAIN}:3478"
echo "  TURN URI: turn:${TURN_DOMAIN}:3478"
echo "  Username: $TURN_USERNAME"
echo "  Password: ${TURN_PASSWORD:0:3}***"
echo ""
echo "📝 ICE Servers JSON:"
echo "$ICE_SERVERS_JSON"
echo ""
echo "🧪 Test TURN Server:"
echo "  python3 scripts/test-turn-server.py"
echo ""
echo "📋 Next Steps:"
echo "  1. Create UDPRoutes for your services in k8s/stunner-manifests.yaml"
echo "  2. Deploy June services with WebRTC config:"
echo "     kubectl apply -f k8s/complete-manifests.yaml"
echo ""
echo "🔍 Debug Commands:"
echo "  kubectl get gateway -n stunner"
echo "  kubectl get svc -n stunner"
echo "  kubectl logs -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator"
echo "  kubectl get pods -n stunner"
echo ""
echo "======================================================"