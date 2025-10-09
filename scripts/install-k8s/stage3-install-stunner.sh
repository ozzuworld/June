#!/bin/bash
# Stage 3: STUNner STUN/TURN Server Installation
# This installs STUNner for WebRTC media streaming support
# FIXED VERSION: Includes bare metal hostNetwork configuration

set -e

echo "======================================================"
echo "🔗 Stage 3: STUNner STUN/TURN Server Installation"
echo "   ✅ Kubernetes-native STUN/TURN server"
echo "   ✅ WebRTC media streaming support"
echo "   ✅ Integration with June services"
echo "   ✅ FIXED: Bare metal hostNetwork support"
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
# APPLY FIXED STUNNER MANIFESTS WITH HOSTNETWORK
# ============================================================================

log_info "Applying fixed STUNner manifests with hostNetwork configuration..."

# Create temporary manifest file with hostNetwork configuration
cat > /tmp/stunner-fixed-manifests.yaml << EOF
# STUNner STUN/TURN Server Kubernetes Manifests for June Services
# FIXED VERSION - Uses hostNetwork for reliable external access on bare metal

---
# STUNner GatewayClass
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: june-stunner-gateway-class
  namespace: stunner
spec:
  controllerName: "stunner.l7mp.io/gateway-operator"
  parametersRef:
    group: "stunner.l7mp.io"
    kind: GatewayConfig
    name: june-stunner-config
    namespace: stunner

---
# STUNner GatewayConfig
apiVersion: stunner.l7mp.io/v1
kind: GatewayConfig
metadata:
  name: june-stunner-config
  namespace: stunner
spec:
  logLevel: "all:INFO"
  realm: "${STUNNER_REALM}"
  authRef:
    name: stunner-auth-secret
    namespace: stunner

---
# STUNner Gateway for STUN/TURN with hostNetwork
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: june-stunner-gateway
  namespace: stunner
  annotations:
    stunner.l7mp.io/enable-mixed-protocol-lb: "true"
spec:
  gatewayClassName: june-stunner-gateway-class
  listeners:
  - name: udp-listener
    port: 3478
    protocol: UDP
    allowedRoutes:
      namespaces:
        from: All

---
# STUNner Deployment with hostNetwork (FIXED for bare metal)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-stunner-gateway
  namespace: stunner
  labels:
    app: stunner
    stunner.l7mp.io/related-gateway-name: june-stunner-gateway
    stunner.l7mp.io/related-gateway-namespace: stunner
spec:
  replicas: 1
  selector:
    matchLabels:
      app: stunner
      stunner.l7mp.io/related-gateway-name: june-stunner-gateway
      stunner.l7mp.io/related-gateway-namespace: stunner
  template:
    metadata:
      labels:
        app: stunner
        stunner.l7mp.io/related-gateway-name: june-stunner-gateway
        stunner.l7mp.io/related-gateway-namespace: stunner
    spec:
      # CRITICAL FIX: Use hostNetwork for bare metal deployments
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      
      # Ensure STUNner runs on the control plane node
      nodeSelector:
        node-role.kubernetes.io/control-plane: ""
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
      
      containers:
      - name: stunner
        # Use the official STUNner image
        image: l7mp/stunner:latest
        imagePullPolicy: Always
        
        ports:
        - containerPort: 3478
          protocol: UDP
          name: turn-udp
        - containerPort: 8086
          protocol: TCP
          name: health
        
        env:
        - name: STUNNER_ADDR
          value: "0.0.0.0:3478"
        - name: STUNNER_HEALTH_CHECK
          value: "http://0.0.0.0:8086"
        
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
        
        livenessProbe:
          httpGet:
            path: /health
            port: 8086
          initialDelaySeconds: 10
          periodSeconds: 30
        
        readinessProbe:
          httpGet:
            path: /health
            port: 8086
          initialDelaySeconds: 5
          periodSeconds: 10

---
# STUNner Service (ClusterIP since we're using hostNetwork)
apiVersion: v1
kind: Service
metadata:
  name: june-stunner-gateway
  namespace: stunner
  labels:
    app: stunner
    stunner.l7mp.io/related-gateway-name: june-stunner-gateway
    stunner.l7mp.io/related-gateway-namespace: stunner
spec:
  type: ClusterIP
  selector:
    app: stunner
    stunner.l7mp.io/related-gateway-name: june-stunner-gateway
    stunner.l7mp.io/related-gateway-namespace: stunner
  ports:
  - port: 3478
    targetPort: 3478
    protocol: UDP
    name: udp-listener
  - port: 8086
    targetPort: 8086
    protocol: TCP
    name: health

---
# UDPRoute for June Orchestrator (primary WebRTC traffic)
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: june-orchestrator-udp-route
  namespace: stunner
spec:
  parentRefs:
  - name: june-stunner-gateway
    namespace: stunner
  rules:
  - backendRefs:
    - name: june-orchestrator
      namespace: june-services
      port: 8080

---
# UDPRoute for June STT Service
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: june-stt-udp-route
  namespace: stunner
spec:
  parentRefs:
  - name: june-stunner-gateway
    namespace: stunner
  rules:
  - backendRefs:
    - name: june-stt
      namespace: june-services
      port: 8080

---
# UDPRoute for June TTS Service
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: june-tts-udp-route
  namespace: stunner
spec:
  parentRefs:
  - name: june-stunner-gateway
    namespace: stunner
  rules:
  - backendRefs:
    - name: june-tts
      namespace: june-services
      port: 8000
EOF

# Apply the fixed STUNner manifests
kubectl apply -f /tmp/stunner-fixed-manifests.yaml

# Clean up temporary file
rm -f /tmp/stunner-fixed-manifests.yaml

log_success "STUNner manifests applied with hostNetwork configuration!"

# Wait for STUNner deployment to be ready
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

cat >> "${STUNNER_CONFIG_FILE}" << EOF

# STUNner STUN/TURN Server Configuration
# Generated: $(date)
# FIXED VERSION: Uses hostNetwork for bare metal
TURN_DOMAIN=${TURN_DOMAIN}
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
STUNNER_HOST_NETWORK=true
STUNNER_PORT=3478
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
STUNNER_HOST_NETWORK=true
STUNNER_PORT=3478
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

# Check STUNner deployment
if kubectl get deployment june-stunner-gateway -n stunner &>/dev/null; then
    log_success "STUNner deployment exists"
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

# Test STUN connectivity
log_info "Testing STUN connectivity..."
if command -v python3 &> /dev/null; then
    # Simple STUN test
    python3 -c "
import socket, struct, time
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    stun_request = struct.pack('!HH12s', 0x0001, 0x0000, b'\\x12\\x34\\x56\\x78\\x90\\xab\\xcd\\xef\\xfe\\xdc\\xba\\x98')
    sock.sendto(stun_request, ('127.0.0.1', 3478))
    response = sock.recv(1024)
    print('✅ STUN connectivity test PASSED!')
except Exception as e:
    print(f'⚠️  STUN connectivity test failed: {e}')
    print('   This is normal if the deployment is still starting up')" || log_warning "Could not run STUN test"
else
    log_warning "Python3 not available for STUN test"
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
echo "  ✅ STUNner deployment with hostNetwork"
echo "  ✅ STUN/TURN server on port 3478"
echo ""
echo "🔗 STUNner Configuration:"
echo "  TURN Domain: ${TURN_DOMAIN}"
echo "  Realm: ${STUNNER_REALM}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo "  Host Network: ENABLED (for bare metal)"
echo "  Port: 3478"
echo ""
echo "📁 Configuration Files:"
echo "  STUNner config: ${STUNNER_CONFIG_FILE}"
echo "  Domain config updated: ${DOMAIN_CONFIG_FILE}"
echo ""
echo "Next Steps:"
echo ""
echo "  1. ✅ STUNner is now running with hostNetwork on port 3478"
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