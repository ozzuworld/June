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
cat > "$CONFIG_DIR/networking.env" << 'CONFIGEOF'
EXTERNAL_IP=$EXTERNAL_IP
TURN_DOMAIN=$TURN_DOMAIN
TURN_USERNAME=$TURN_USERNAME
TURN_PASSWORD=$TURN_PASSWORD
INSTALL_DATE="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
CONFIGEOF
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

kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml

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

kubectl create namespace stunner-system || true
kubectl create namespace stunner || true

if ! command -v helm &> /dev/null; then
    log_info "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

helm repo add stunner https://l7mp.io/stunner
helm repo update

if helm list -n stunner-system | grep -q stunner-gateway-operator; then
    log_success "STUNner operator already installed"
else
    log_info "Installing STUNner operator (this may take 5-10 minutes)..."
    
    helm install stunner-gateway-operator stunner/stunner-gateway-operator \
        --namespace=stunner-system \
        --set stunnerGatewayOperator.dataplane.spec.replicas=1 \
        --timeout=15m
    
    log_info "Waiting for operator to be ready..."
    sleep 30
    
    for i in {1..60}; do
        RUNNING=$(kubectl get pods -n stunner-system --no-headers 2>/dev/null | grep "Running" | wc -l)
        if [ "$RUNNING" -ge 1 ]; then
            log_success "STUNner operator is running!"
            break
        fi
        
        if [ $((i % 10)) -eq 0 ]; then
            log_info "Waiting for operator pods... (${i}/60)"
        fi
        sleep 10
    done
    
    log_success "STUNner operator installed!"
fi

# ============================================================================
# STUNNER GATEWAY CONFIGURATION
# ============================================================================

log_info "⚙️  Configuring STUNner Gateway..."

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

cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: june-stunner-gateway
  namespace: stunner
  annotations:
    stunner.l7mp.io/service-type: LoadBalancer
    stunner.l7mp.io/enable-mixed-protocol-lb: "true"
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

log_info "Waiting for Gateway to be ready..."
sleep 20

for i in {1..30}; do
    ACCEPTED=$(kubectl get gateway june-stunner-gateway -n stunner -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}' 2>/dev/null)
    
    if [ "$ACCEPTED" = "True" ]; then
        log_success "Gateway is ready!"
        break
    fi
    
    if [ $((i % 5)) -eq 0 ]; then
        log_info "Waiting for gateway... (${i}/30)"
    fi
    sleep 10
done

GATEWAY_IP=$(kubectl get gateway june-stunner-gateway -n stunner -o jsonpath='{.status.addresses[0].value}' 2>/dev/null || echo "$EXTERNAL_IP")
log_success "STUNner Gateway IP: $GATEWAY_IP"

# ============================================================================
# REFERENCEGRANT FOR CROSS-NAMESPACE ACCESS
# ============================================================================

log_info "🔐 Creating ReferenceGrant..."

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
# ICE SERVERS CONFIGURATION
# ============================================================================

log_info "📝 Generating ICE servers configuration..."

ICE_SERVERS_JSON="[{\"urls\":[\"stun:${TURN_DOMAIN}:3478\"]},{\"urls\":[\"turn:${TURN_DOMAIN}:3478\"],\"username\":\"${TURN_USERNAME}\",\"credential\":\"${TURN_PASSWORD}\"}]"

cat > "$CONFIG_DIR/ice-servers.json" << EOF
$ICE_SERVERS_JSON
EOF

log_success "ICE servers configuration saved!"

# ============================================================================
# WEBRTC CONFIGMAP CREATION
# ============================================================================

log_info "📝 Creating WebRTC ConfigMap..."

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

echo ""
echo "======================================================"
log_success "Networking Setup Complete!"
echo "======================================================"
echo ""
echo "✅ Installed Components:"
echo "  • MetalLB (IP: $EXTERNAL_IP)"
echo "  • Gateway API v1"
echo "  • STUNner Operator"
echo "  • STUNner Gateway"
echo "  • WebRTC ConfigMap (all keys present)"
echo ""
echo "🔗 STUNner Configuration:"
echo "  Gateway: june-stunner-gateway"
echo "  Gateway IP: $GATEWAY_IP"
echo "  STUN URI: stun:${TURN_DOMAIN}:3478"
echo "  TURN URI: turn:${TURN_DOMAIN}:3478"
echo ""
echo "📋 Next Steps:"
echo "  kubectl apply -f k8s/complete-manifests.yaml"
echo ""
echo "======================================================"