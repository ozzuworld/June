#!/bin/bash
# June Platform - Complete Installation Script
# Installs K8s + Helm + June Platform + LiveKit + STUNner
# This is your main installation script for fresh VMs

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
echo "June Platform - Complete Installation"
echo "Fresh VM -> Full June Platform + LiveKit"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install.sh)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration file
CONFIG_FILE="${SCRIPT_DIR}/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE
    
Please create it first:
  cp config.env.example config.env
  nano config.env
"
fi

log "Loading configuration from: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
REQUIRED_VARS=(
    "DOMAIN"
    "LETSENCRYPT_EMAIL"
    "GEMINI_API_KEY"
    "CLOUDFLARE_TOKEN"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        error "Required variable $var is not set in $CONFIG_FILE"
    fi
done

success "Configuration loaded"
log "Domain: $DOMAIN"

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

install_prerequisites() {
    log "Step 1/9: Installing prerequisites..."
    
    apt-get update -qq
    
    apt-get install -y \
        curl \
        wget \
        git \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        jq \
        openssl \
        > /dev/null 2>&1
    
    success "Prerequisites installed"
}

# ============================================================================
# STEP 2: Install Docker
# ============================================================================

install_docker() {
    log "Step 2/9: Installing Docker..."
    
    if command -v docker &> /dev/null; then
        success "Docker already installed"
        return
    fi
    
    curl -fsSL https://get.docker.com | bash > /dev/null 2>&1
    
    systemctl stop containerd
    mkdir -p /etc/containerd
    containerd config default > /etc/containerd/config.toml
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    systemctl restart containerd
    systemctl enable containerd > /dev/null 2>&1
    
    success "Docker installed"
}

# ============================================================================
# STEP 3: Install Kubernetes
# ============================================================================

install_kubernetes() {
    log "Step 3/9: Installing Kubernetes..."
    
    if kubectl cluster-info &> /dev/null; then
        success "Kubernetes already running"
        return
    fi
    
    # Kernel modules
    modprobe br_netfilter
    cat > /etc/modules-load.d/k8s.conf << EOF
br_netfilter
EOF
    
    cat > /etc/sysctl.d/k8s.conf << EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
    sysctl --system > /dev/null 2>&1
    
    # Add Kubernetes apt repository
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    
    # Install Kubernetes components
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    apt-mark hold kubelet kubeadm kubectl
    
    # Initialize cluster
    log "Initializing Kubernetes cluster..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init \
        --pod-network-cidr=10.244.0.0/16 \
        --apiserver-advertise-address=$INTERNAL_IP \
        --cri-socket=unix:///var/run/containerd/containerd.sock \
        > /dev/null 2>&1
    
    # Setup kubectl
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    # Install Flannel CNI
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    
    # Remove taints so pods can run on control plane
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    
    # Wait for nodes to be ready
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    
    success "Kubernetes cluster ready"
}

# ============================================================================
# STEP 4: Install Infrastructure (ingress-nginx, cert-manager)
# ============================================================================

install_infrastructure() {
    log "Step 4/9: Installing infrastructure..."
    
    # Install ingress-nginx
    if ! kubectl get namespace ingress-nginx &> /dev/null; then
        log "Installing ingress-nginx..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml > /dev/null 2>&1
        sleep 10
        
        # Enable host networking for bare metal
        kubectl patch deployment ingress-nginx-controller -n ingress-nginx \
            --type='json' \
            -p='[{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},{"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}]' \
            > /dev/null 2>&1
        
        log "Waiting for ingress-nginx..."
        kubectl wait --for=condition=available --timeout=300s deployment/ingress-nginx-controller -n ingress-nginx > /dev/null 2>&1
        success "ingress-nginx installed"
    else
        success "ingress-nginx already installed"
    fi
    
    # Install cert-manager
    if ! kubectl get namespace cert-manager &> /dev/null; then
        log "Installing cert-manager..."
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml > /dev/null 2>&1
        kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager > /dev/null 2>&1
        success "cert-manager installed"
    else
        success "cert-manager already installed"
    fi
    
    # Wait for CRDs to be established
    log "Waiting for cert-manager CRDs..."
    for i in {1..60}; do
        if kubectl get crd clusterissuers.cert-manager.io &> /dev/null && \
           kubectl get crd certificates.cert-manager.io &> /dev/null; then
            break
        fi
        sleep 2
    done
    
    # Create Cloudflare secret for DNS challenges
    kubectl create secret generic cloudflare-api-token \
        --from-literal=api-token="$CLOUDFLARE_TOKEN" \
        --namespace=cert-manager \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Create ClusterIssuer for Let's Encrypt
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsNames:
        - "$DOMAIN"
        - "*.$DOMAIN"
EOF
    
    # Create storage for PostgreSQL
    mkdir -p /opt/june-postgresql-data
    chmod 755 /opt/june-postgresql-data
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF
    
    success "Infrastructure ready"
}

# ============================================================================
# STEP 5: Install Helm
# ============================================================================

install_helm() {
    log "Step 5/9: Installing Helm..."
    
    if command -v helm &> /dev/null; then
        success "Helm already installed"
        return
    fi
    
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    success "Helm installed"
}

# ============================================================================
# STEP 6: Install STUNner
# ============================================================================

install_stunner() {
    log "Step 6/9: Installing STUNner..."
    
    # Install Gateway API
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml > /dev/null 2>&1
    
    # Wait for Gateway API CRDs
    for i in {1..30}; do
        if kubectl get crd gatewayclasses.gateway.networking.k8s.io &>/dev/null; then
            break
        fi
        sleep 2
    done
    
    # Add STUNner Helm repo
    helm repo add stunner https://l7mp.io/stunner > /dev/null 2>&1
    helm repo update > /dev/null 2>&1
    
    # Install STUNner operator
    helm install stunner stunner/stunner \
        --create-namespace \
        --namespace=stunner-system \
        --wait \
        --timeout=10m > /dev/null 2>&1
    
    # Apply STUNner configuration from k8s/stunner/
    if [ -d "${SCRIPT_DIR}/k8s/stunner" ]; then
        log "Applying STUNner configuration..."
        
        # Create secret with proper credentials
        kubectl create secret generic stunner-auth-secret \
            --from-literal=type=static \
            --from-literal=username="${TURN_USERNAME:-june-user}" \
            --from-literal=password="${STUNNER_PASSWORD:-Pokemon123!}" \
            --namespace=stunner \
            --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
        
        # Apply other STUNner resources
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/00-namespaces.yaml" > /dev/null 2>&1 || true
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/20-dataplane-hostnet.yaml" > /dev/null 2>&1 || true
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/30-gatewayconfig.yaml" > /dev/null 2>&1 || true
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/40-gatewayclass.yaml" > /dev/null 2>&1 || true
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/50-gateway.yaml" > /dev/null 2>&1 || true
    fi
    
    success "STUNner installed"
}

# ============================================================================
# STEP 7: Install LiveKit
# ============================================================================

install_livekit() {
    log "Step 7/9: Installing LiveKit..."
    
    # Create media namespace
    kubectl create namespace media --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Add LiveKit Helm repo
    helm repo add livekit https://helm.livekit.io > /dev/null 2>&1
    helm repo update > /dev/null 2>&1
    
    # Install LiveKit with configuration from k8s/livekit/
    if [ -f "${SCRIPT_DIR}/k8s/livekit/livekit-values.yaml" ]; then
        helm upgrade --install livekit livekit/livekit-server \
            --namespace media \
            --values "${SCRIPT_DIR}/k8s/livekit/livekit-values.yaml" \
            --wait \
            --timeout=10m > /dev/null 2>&1
    else
        # Fallback basic configuration
        helm upgrade --install livekit livekit/livekit-server \
            --namespace media \
            --set server.replicas=1 \
            --wait \
            --timeout=10m > /dev/null 2>&1
    fi
    
    # Apply additional LiveKit resources
    if [ -f "${SCRIPT_DIR}/k8s/livekit/livekit-udp-svc.yaml" ]; then
        kubectl apply -f "${SCRIPT_DIR}/k8s/livekit/livekit-udp-svc.yaml" > /dev/null 2>&1
    fi
    
    # Apply UDPRoute for LiveKit
    if [ -f "${SCRIPT_DIR}/k8s/stunner/60-udproute-livekit.yaml" ]; then
        kubectl apply -f "${SCRIPT_DIR}/k8s/stunner/60-udproute-livekit.yaml" > /dev/null 2>&1
    fi
    
    success "LiveKit installed"
}

# ============================================================================
# STEP 8: Deploy June Platform (Core Services)
# ============================================================================

deploy_june_platform() {
    log "Step 8/9: Deploying June Platform..."
    
    HELM_CHART="$SCRIPT_DIR/helm/june-platform"
    
    if [ ! -d "$HELM_CHART" ]; then
        error "Helm chart not found at: $HELM_CHART"
    fi
    
    # Ensure Chart.yaml exists
    if [ ! -f "$HELM_CHART/Chart.yaml" ] && [ -f "$HELM_CHART/chart.yaml" ]; then
        mv "$HELM_CHART/chart.yaml" "$HELM_CHART/Chart.yaml"
    fi
    
    # Create june-services namespace
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Detect GPU availability
    GPU_AVAILABLE="false"
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_AVAILABLE="true"
        log "GPU detected - STT and TTS will be enabled"
    else
        log "No GPU detected - STT and TTS will be disabled"
    fi
    
    # Deploy June Platform
    helm upgrade --install june-platform "$HELM_CHART" \
        --namespace june-services \
        --set global.domain="$DOMAIN" \
        --set certificate.email="$LETSENCRYPT_EMAIL" \
        --set secrets.geminiApiKey="$GEMINI_API_KEY" \
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN" \
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}" \
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}" \
        --set stt.enabled="$GPU_AVAILABLE" \
        --set tts.enabled="$GPU_AVAILABLE" \
        --set certificate.enabled=true \
        --timeout 15m > /dev/null 2>&1
    
    # Wait for core services
    log "Waiting for core services..."
    kubectl wait --for=condition=available --timeout=300s \
        deployment/june-orchestrator -n june-services > /dev/null 2>&1 || warn "Orchestrator timeout"
    kubectl wait --for=condition=available --timeout=300s \
        deployment/june-idp -n june-services > /dev/null 2>&1 || warn "IDP timeout"
    
    success "June Platform deployed"
}

# ============================================================================
# STEP 9: Final Configuration
# ============================================================================

final_setup() {
    log "Step 9/9: Final setup..."
    
    # Create ReferenceGrant for cross-namespace access
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-media
  namespace: media
spec:
  from:
  - group: stunner.l7mp.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF
    
    success "Final setup complete"
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    install_prerequisites
    install_docker
    install_kubernetes
    install_infrastructure
    install_helm
    install_stunner
    install_livekit
    deploy_june_platform
    final_setup
    
    # Get external IP
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    success "June Platform Installation Complete!"
    echo "=========================================="
    echo ""
    echo "📋 Your Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    if [ "$GPU_AVAILABLE" = "true" ]; then
        echo "  STT:        https://stt.$DOMAIN"
        echo "  TTS:        https://tts.$DOMAIN"
    fi
    echo ""
    echo "🎮 WebRTC Services:"
    echo "  LiveKit:    livekit.media.svc.cluster.local"
    echo "  TURN:       turn:${EXTERNAL_IP}:3478"
    echo ""
    echo "🌐 DNS Configuration:"
    echo "  Point these records to: $EXTERNAL_IP"
    echo "    $DOMAIN           A    $EXTERNAL_IP"
    echo "    *.$DOMAIN         A    $EXTERNAL_IP"
    echo ""
    echo "🔐 Access Credentials:"
    echo "  Keycloak Admin: https://idp.$DOMAIN/admin"
    echo "    Username: admin"
    echo "    Password: ${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
    echo ""
    echo "  TURN Server: turn:${EXTERNAL_IP}:3478"
    echo "    Username: ${TURN_USERNAME:-june-user}"
    echo "    Password: ${STUNNER_PASSWORD:-Pokemon123!}"
    echo ""
    echo "📊 Status Check:"
    echo "  kubectl get pods -n june-services   # Core services"
    echo "  kubectl get pods -n media            # LiveKit"
    echo "  kubectl get gateway -n stunner       # STUNner"
    echo ""
    echo "=========================================="
}

main "$@"