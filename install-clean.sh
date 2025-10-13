#!/bin/bash
# June Platform - Clean Installation Script
# One script to install everything: K8s + Helm + June Platform (without WebRTC)
# WebRTC is now handled separately via LiveKit + STUNner

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
log_info() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "=========================================="
echo "June Platform - Core Installation"
echo "(WebRTC services installed separately)"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install-clean.sh)"
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
log "Email: $LETSENCRYPT_EMAIL"

# Certificate backup directory
BACKUP_DIR="/root/.june-certs"
CERT_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
USING_BACKUP_CERT="false"

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

install_prerequisites() {
    log "Step 1/6: Installing prerequisites..."
    
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
    log "Step 2/6: Installing Docker..."
    
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
    log "Step 3/6: Installing Kubernetes..."
    
    if kubectl cluster-info &> /dev/null; then
        success "Kubernetes already running"
        return
    fi
    
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
    
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    apt-mark hold kubelet kubeadm kubectl
    
    log "Initializing Kubernetes cluster..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init \
        --pod-network-cidr=10.244.0.0/16 \
        --apiserver-advertise-address=$INTERNAL_IP \
        --cri-socket=unix:///var/run/containerd/containerd.sock \
        > /dev/null 2>&1
    
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    
    success "Kubernetes cluster ready"
}

# ============================================================================
# STEP 4: Install Infrastructure (ingress-nginx, cert-manager)
# ============================================================================

install_infrastructure() {
    log "Step 4/6: Installing infrastructure components..."
    
    # Install ingress-nginx
    if ! kubectl get namespace ingress-nginx &> /dev/null; then
        log "Installing ingress-nginx..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml > /dev/null 2>&1
        sleep 10
        
        kubectl patch deployment ingress-nginx-controller -n ingress-nginx \
            --type='json' \
            -p='[{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},{"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}]' \
            > /dev/null 2>&1
        
        log "Waiting for ingress-nginx..."
        sleep 30
        success "ingress-nginx installed"
        
    else
        success "ingress-nginx already installed"
    fi
    
    # Install cert-manager
    if ! kubectl get namespace cert-manager &> /dev/null; then
        log "Installing cert-manager..."
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml > /dev/null 2>&1
        
        log "Waiting for cert-manager pods..."
        sleep 30
        success "cert-manager installed"
    else
        success "cert-manager already installed"
    fi
    
    # Wait for cert-manager CRDs
    log "Waiting for cert-manager CRDs..."
    sleep 15
    
    for i in {1..60}; do
        if kubectl get crd clusterissuers.cert-manager.io &> /dev/null && \
           kubectl get crd certificates.cert-manager.io &> /dev/null; then
            success "cert-manager CRDs ready"
            break
        fi
        sleep 2
    done
    
    # Create Cloudflare secret
    kubectl create namespace cert-manager --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    kubectl create secret generic cloudflare-api-token \
        --from-literal=api-token="$CLOUDFLARE_TOKEN" \
        --namespace=cert-manager \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Create ClusterIssuer
    log "Creating ClusterIssuer..."
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
    
    # Create local storage
    log "Setting up storage..."
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
    log "Step 5/6: Verifying Helm..."
    
    if helm version &> /dev/null; then
        success "Helm ready"
        return
    fi
    
    log "Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    
    if helm version &> /dev/null; then
        success "Helm installed"
    else
        error "Helm installation failed"
    fi
}

# ============================================================================
# STEP 6: Deploy June Platform (Core Services Only)
# ============================================================================

deploy_june() {
    log "Step 6/6: Deploying June Platform (Core Services)..."
    
    HELM_CHART="$SCRIPT_DIR/helm/june-platform"
    
    if [ ! -d "$HELM_CHART" ]; then
        error "Helm chart not found at: $HELM_CHART"
    fi
    
    if [ ! -f "$HELM_CHART/Chart.yaml" ]; then
        if [ -f "$HELM_CHART/chart.yaml" ]; then
            mv "$HELM_CHART/chart.yaml" "$HELM_CHART/Chart.yaml"
        else
            error "Chart.yaml not found"
        fi
    fi
    
    # Ensure june-services namespace exists
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Detect GPU availability
    GPU_AVAILABLE="false"
    
    # Check manual override first
    if [ "${ENABLE_STT:-auto}" = "true" ] || [ "${ENABLE_TTS:-auto}" = "true" ]; then
        GPU_AVAILABLE="true"
        log_info "GPU services manually enabled"
    elif [ "${ENABLE_STT:-auto}" = "false" ] && [ "${ENABLE_TTS:-auto}" = "false" ]; then
        GPU_AVAILABLE="false"
        log_info "GPU services manually disabled"
    else
        # Auto-detect
        if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
            GPU_AVAILABLE="true"
            log_info "GPU detected - STT and TTS will be enabled"
        else
            GPU_AVAILABLE="false"
            log_info "No GPU detected - STT and TTS will be disabled"
            warn "Voice services (STT/TTS) require GPU support and will be skipped"
        fi
    fi
    
    HELM_ARGS=(
        --namespace june-services
        --set global.domain="$DOMAIN"
        --set certificate.email="$LETSENCRYPT_EMAIL"
        --set secrets.geminiApiKey="$GEMINI_API_KEY"
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN"
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}"
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
        --set stt.enabled="$GPU_AVAILABLE"
        --set tts.enabled="$GPU_AVAILABLE"
        --set certificate.enabled=true
        --timeout 15m
    )
    
    log "Deploying core services..."
    
    set +e
    helm upgrade --install june-platform "$HELM_CHART" "${HELM_ARGS[@]}" 2>&1 | tee /tmp/helm-deploy.log
    HELM_EXIT_CODE=$?
    set -e
    
    # Wait for critical services
    log_info "Waiting for core services to start..."
    sleep 10
    
    # Wait for orchestrator and IDP (core services)
    for i in {1..60}; do
        ORCH_READY=$(kubectl get pods -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
        IDP_READY=$(kubectl get pods -n june-services -l app=june-idp -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
        
        if [ "$ORCH_READY" = "Running" ] && [ "$IDP_READY" = "Running" ]; then
            success "Core services are running"
            break
        fi
        
        if [ $((i % 10)) -eq 0 ]; then
            log_info "Still waiting for core services... ($i/60)"
        fi
        sleep 5
    done
    
    if [ $HELM_EXIT_CODE -eq 0 ]; then
        success "June Platform deployed"
    else
        log_info "Verifying deployment status..."
        sleep 3
        
        if kubectl get deployment -n june-services june-orchestrator &>/dev/null; then
            success "June Platform deployed (Helm had warnings)"
        else
            error "Deployment failed. Check /tmp/helm-deploy.log"
        fi
    fi
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
    deploy_june
    
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    success "Core Installation Complete!"
    echo "=========================================="
    echo ""
    echo "📋 Your Core Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    if [ "$GPU_AVAILABLE" = "true" ]; then
        echo "  STT:        https://stt.$DOMAIN"
        echo "  TTS:        https://tts.$DOMAIN"
    fi
    echo ""
    echo "🌐 DNS Configuration:"
    echo "  Point these records to: $EXTERNAL_IP"
    echo "    $DOMAIN           A    $EXTERNAL_IP"
    echo "    *.$DOMAIN         A    $EXTERNAL_IP"
    echo ""
    echo "🔐 Keycloak Admin:"
    echo "  URL:        https://idp.$DOMAIN/admin"
    echo "  Username:   admin"
    echo "  Password:   ${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
    echo ""
    echo "📊 Check Status:"
    echo "  kubectl get pods -n june-services"
    echo ""
    echo "🎯 Next Steps:"
    echo "  For WebRTC support, run:"
    echo "    sudo ./install-livekit.sh"
    echo ""
    echo "=========================================="
}

main "$@"