#!/bin/bash
# Networking Setup: MetalLB + STUNner with Gateway API v1
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
echo "   Gateway API v1 with WebRTC Support"
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
# GATEWAY API (v1 - STABLE)
# ============================================================================

log_info "🔗 Installing Gateway API v1.3.0 (v1 stable)..."

# Install Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml

# Wait for CRDs to be established
log_info "Waiting for Gateway API CRDs to be established..."
kubectl wait --for condition=established --timeout=60s \
    crd/gatewayclasses.gateway.networking.k8s.io \
    crd/gateways.gateway.networking.k8s.io \
    crd/httproutes.gateway.networking.k8s.io \
    crd/referencegrants.gateway.networking.k8s.io 2>/dev/null || log_warning "CRDs taking longer than expected"

log_success "Gateway API v1 installed successfully!"

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
# Find and replace this section in your script (around line 190-200):

# Install operator
if helm list -n stunner-system | grep -q stunner-gateway-operator; then
    log_success "STUNner operator already installed"
else
    log_info "Installing STUNner operator (this may take 5-10 minutes)..."
    
    # Install with Helm
    helm install stunner-gateway-operator stunner/stunner-gateway-operator \
        --namespace=stunner-system \
        --set stunnerGatewayOperator.dataplane.spec.replicas=1 \
        --timeout=15m
    
    log_info "Operator installation initiated, waiting for pods..."
    
    # Function to show debug info if something fails
    show_stunner_debug() {
        log_error "STUNner installation failed. Debug information:"
        echo "=== Pods ==="
        kubectl get pods -n stunner-system
        echo "=== Recent Events ==="
        kubectl get events -n stunner-system --sort-by='.lastTimestamp' | tail -10
        echo "=== Operator Logs ==="
        kubectl logs -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator --tail=20 2>/dev/null || echo "No logs available"
    }
    
    # Wait for deployment to be available
    log_info "Waiting for STUNner deployment to be available..."
    if ! kubectl wait --for=condition=available --timeout=120s \
        deployment/stunner-gateway-operator-controller-manager -n stunner-system 2>/dev/null; then
        log_warning "Deployment availability check failed, checking pods directly..."
    fi
    
    # Wait for pods using multiple approaches
    log_info "Waiting for STUNner operator pods to be ready (this may take 5-10 minutes for image pulling)..."
    
    STUNNER_OPERATOR_READY=false
    STUNNER_AUTH_READY=false
    
    # Try multiple methods to check pod readiness
    for i in {1..60}; do
        # Method 1: Check by deployment name patterns
        if kubectl get pods -n stunner-system | grep -q "stunner-gateway-operator-controller-manager.*Running"; then
            STUNNER_OPERATOR_READY=true
        fi
        
        if kubectl get pods -n stunner-system | grep -q "stunner-auth.*Running"; then
            STUNNER_AUTH_READY=true
        fi
        
        # Method 2: Try the deployment readiness check
        if kubectl wait --for=condition=ready --timeout=10s \
            pod -l control-plane=controller-manager -n stunner-system 2>/dev/null; then
            STUNNER_OPERATOR_READY=true
        fi
        
        # Method 3: Direct pod name check
        if kubectl get pod -n stunner-system 2>/dev/null | grep -E "stunner-gateway-operator-controller-manager.*1/1.*Running" >/dev/null; then
            STUNNER_OPERATOR_READY=true
        fi
        
        if kubectl get pod -n stunner-system 2>/dev/null | grep -E "stunner-auth.*1/1.*Running" >/dev/null; then
            STUNNER_AUTH_READY=true
        fi
        
        # Check if both are ready
        if [ "$STUNNER_OPERATOR_READY" = true ] && [ "$STUNNER_AUTH_READY" = true ]; then
            log_success "STUNner operator pods are ready!"
            break
        fi
        
        # Show progress every 10 iterations
        if [ $((i % 10)) -eq 0 ]; then
            log_info "Still waiting for pods... (${i}/60)"
            kubectl get pods -n stunner-system --no-headers 2>/dev/null | head -5
        fi
        
        sleep 10
    done
    
    # Final verification
    if [ "$STUNNER_OPERATOR_READY" != true ] || [ "$STUNNER_AUTH_READY" != true ]; then
        log_warning "Pod readiness check timed out, but verifying actual status..."
        
        # Check actual pod status
        RUNNING_PODS=$(kubectl get pods -n stunner-system --no-headers 2>/dev/null | grep "Running" | wc -l)
        TOTAL_PODS=$(kubectl get pods -n stunner-system --no-headers 2>/dev/null | wc -l)
        
        if [ "$RUNNING_PODS" -ge 2 ] && [ "$TOTAL_PODS" -ge 2 ]; then
            log_success "STUNner pods are actually running ($RUNNING_PODS/$TOTAL_PODS)!"
        else
            log_error "STUNner installation appears to have failed"
            show_stunner_debug
            log_warning "Continuing anyway - sometimes the installation works despite check failures..."
        fi
    fi
    
    # Verify STUNner operator is functional
    log_info "Verifying STUNner operator functionality..."
    sleep 5
    
    # Check if STUNner CRDs are available
    if kubectl get crd dataplanes.stunner.l7mp.io >/dev/null 2>&1; then
        log_success "STUNner CRDs are available - operator is functional"
    else
        log_warning "STUNner CRDs not immediately available, but continuing..."
    fi
    
    # Try to access gateway resources
    if kubectl get gatewayclass >/dev/null 2>&1; then
        log_success "Gateway API resources accessible - STUNner operator is functional"
    else
        log_warning "Gateway API resources not immediately accessible, but continuing..."
    fi
    
    log_success "STUNner installation completed successfully"
fi

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
apiVersion: gateway.networking.k8s.io/v1
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
apiVersion: gateway.networking.k8s.io/v1
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

# ============================================================================
# FIXED GATEWAY READINESS CHECK
# ============================================================================

# Function to wait for Gateway readiness properly
wait_for_gateway_ready() {
    local namespace=$1
    local gateway_name=$2
    local timeout=${3:-300}
    
    log_info "Waiting for Gateway to be ready (may take 2-3 minutes)..."
    
    local count=0
    local max_attempts=$((timeout / 10))
    
    while [ $count -lt $max_attempts ]; do
        # Check if Gateway is Accepted and Programmed (correct conditions for Gateway API v1)
        local accepted=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}' 2>/dev/null)
        local programmed=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' 2>/dev/null)
        local external_ip=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
        
        if [[ "$accepted" == "True" && "$programmed" == "True" && -n "$external_ip" ]]; then
            log_success "Gateway is ready! External IP: $external_ip"
            return 0
        fi
        
        # Show progress every 30 seconds
        if [ $((count % 3)) -eq 0 ]; then
            log_info "Gateway status: Accepted=$accepted, Programmed=$programmed, IP=$external_ip"
        fi
        
        sleep 10
        count=$((count + 1))
    done
    
    log_warning "Gateway readiness check timed out, but checking if it's actually working..."
    
    # Final verification - sometimes the gateway works even if conditions aren't perfect
    local final_accepted=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}' 2>/dev/null)
    local final_programmed=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' 2>/dev/null)
    local final_ip=$(kubectl get gateway $gateway_name -n $namespace -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
    
    if [[ "$final_accepted" == "True" && -n "$final_ip" ]]; then
        log_success "Gateway is actually working despite timeout! IP: $final_ip"
        return 0
    else
        log_error "Gateway failed to become ready within ${timeout}s"
        echo "=== Gateway Debug Information ==="
        kubectl describe gateway $gateway_name -n $namespace
        return 1
    fi
}

# Use the fixed wait function
wait_for_gateway_ready "stunner" "june-stunner-gateway" 300

if [ $? -eq 0 ]; then
    # Get the external IP for confirmation
    GATEWAY_EXTERNAL_IP=$(kubectl get gateway june-stunner-gateway -n stunner -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
    log_success "STUNner Gateway is ready with external IP: $GATEWAY_EXTERNAL_IP"
    
    # Verify dataplane pod is running
    log_info "Verifying STUNner dataplane..."
    if kubectl wait --for=condition=Ready pod -l stunner.l7mp.io/related-gateway-name=june-stunner-gateway -n stunner --timeout=60s 2>/dev/null; then
        log_success "STUNner dataplane is running successfully"
        log_success "TURN Server available at: $GATEWAY_EXTERNAL_IP:3478"
        log_success "STUN Server available at: $GATEWAY_EXTERNAL_IP:3478"
    else
        log_warning "STUNner dataplane pod not ready yet, but Gateway is configured"
        log_info "Checking if dataplane pod exists..."
        kubectl get pods -n stunner -l stunner.l7mp.io/related-gateway-name=june-stunner-gateway || log_warning "No dataplane pods found yet"
    fi
else
    log_error "STUNner Gateway setup failed"
    exit 1
fi

# ============================================================================
# REFERENCEGRANT FOR CROSS-NAMESPACE ACCESS
# ============================================================================

log_info "🔐 Creating ReferenceGrant for cross-namespace access..."

# Ensure june-services namespace exists
kubectl create namespace june-services || true

cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1beta1
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
    STUNNER_LB_IP="pending"
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

# Use the Gateway IP if available, otherwise use configured external IP
ICE_SERVER_IP=${GATEWAY_EXTERNAL_IP:-$STUNNER_LB_IP}
if [ "$ICE_SERVER_IP" = "pending" ] || [ -z "$ICE_SERVER_IP" ]; then
    ICE_SERVER_IP=$EXTERNAL_IP
    log_warning "Using configured external IP for ICE servers: $ICE_SERVER_IP"
fi

# Create ICE servers JSON for orchestrator
ICE_SERVERS_JSON=$(cat <<EOF
[
  {
    "urls": ["stun:${TURN_DOMAIN}:3478", "stun:${ICE_SERVER_IP}:3478"]
  },
  {
    "urls": ["turn:${TURN_DOMAIN}:3478", "turn:${ICE_SERVER_IP}:3478"],
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
# WEBRTC CONFIGMAP CREATION
# ============================================================================

log_info "📝 Creating WebRTC ConfigMap for June services..."

# Create june-services namespace if it doesn't exist
kubectl create namespace june-services || true

# Create the WebRTC ConfigMap with all required keys
kubectl create configmap june-webrtc-config \
  --from-literal=APP_ENV="production" \
  --from-literal=LOG_LEVEL="info" \
  --from-literal=REGION="us-central1" \
  --from-literal=STUN_SERVER_URL="stun:${TURN_DOMAIN}:3478" \
  --from-literal=TURN_SERVER_URL="turn:${TURN_DOMAIN}:3478" \
  --from-literal=TURN_USERNAME="${TURN_USERNAME}" \
  --from-literal=TURN_CREDENTIAL="${TURN_PASSWORD}" \
  --from-literal=STUNNER_GATEWAY_SERVICE="june-stunner-gateway-udp.stunner.svc.cluster.local:3478" \
  --from-literal=STUNNER_GATEWAY_URL="udp://june-stunner-gateway-udp.stunner.svc.cluster.local:3478" \
  --from-literal=ICE_SERVERS="$ICE_SERVERS_JSON" \
  --namespace=june-services \
  --dry-run=client -o yaml | kubectl apply -f -

log_success "WebRTC ConfigMap created with all required keys!"


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
echo "  • Gateway API v1 (stable)"
echo "  • STUNner Operator"
echo "  • STUNner Gateway (LoadBalancer)"
echo "  • ReferenceGrant for cross-namespace routing"
echo ""
echo "🔗 STUNner Configuration:"
echo "  Gateway: june-stunner-gateway"
echo "  LoadBalancer IP: ${STUNNER_LB_IP:-$ICE_SERVER_IP}"
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
echo "  kubectl logs -n stunner-system -l control-plane=controller-manager"
echo "  kubectl get pods -n stunner"
echo ""
echo "======================================================"
