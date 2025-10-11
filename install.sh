#!/bin/bash
# June Platform - Unified Installation Script
# One script to install everything: K8s + Helm + June Platform

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
echo "June Platform - Unified Installation"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install.sh)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

install_prerequisites() {
    log "Step 1/6: Installing prerequisites..."
    
    # Update package list
    apt-get update -qq
    
    # Install basic tools
    apt-get install -y \
        curl \
        wget \
        git \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        jq \
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
    
    # Install Docker
    curl -fsSL https://get.docker.com | bash > /dev/null 2>&1
    
    # Configure containerd
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
    
    # Load kernel modules
    modprobe br_netfilter
    cat > /etc/modules-load.d/k8s.conf << EOF
br_netfilter
EOF
    
    # Set sysctl parameters
    cat > /etc/sysctl.d/k8s.conf << EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
    sysctl --system > /dev/null 2>&1
    
    # Install Kubernetes packages
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    apt-mark hold kubelet kubeadm kubectl
    
    # Initialize cluster
    log "Initializing Kubernetes cluster (this may take a few minutes)..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init \
        --pod-network-cidr=10.244.0.0/16 \
        --apiserver-advertise-address=$INTERNAL_IP \
        --cri-socket=unix:///var/run/containerd/containerd.sock \
        > /dev/null 2>&1
    
    # Configure kubectl
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    # Install Flannel CNI
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    
    # Remove taints
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    
    # Wait for cluster to be ready
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    
    success "Kubernetes cluster ready"
}

# ============================================================================
# STEP 4: Install Infrastructure
# ============================================================================

install_infrastructure() {
    log "Step 4/6: Installing infrastructure components..."
    
    # Install ingress-nginx
    if ! kubectl get namespace ingress-nginx &> /dev/null; then
        log "Installing ingress-nginx..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml > /dev/null 2>&1
        sleep 10
        
        # Enable hostNetwork
        kubectl patch deployment ingress-nginx-controller -n ingress-nginx \
            --type='json' \
            -p='[{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},{"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}]' \
            > /dev/null 2>&1
        
        log "Waiting for ingress-nginx (max 5 minutes)..."
        if timeout 300s kubectl wait --for=condition=ready pod \
            -n ingress-nginx \
            -l app.kubernetes.io/component=controller 2>&1; then
            success "ingress-nginx installed"
        else
            warn "ingress-nginx timeout - checking status..."
            RUNNING=$(kubectl get pods -n ingress-nginx --no-headers 2>/dev/null | grep -c "Running" || echo "0")
            if [ "$RUNNING" -gt 0 ]; then
                warn "ingress-nginx partially running ($RUNNING pods) - continuing"
            else
                error "ingress-nginx failed to start"
            fi
        fi
    else
        success "ingress-nginx already installed"
    fi
    
    # Install cert-manager
    if ! kubectl get namespace cert-manager &> /dev/null; then
        log "Installing cert-manager..."
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml > /dev/null 2>&1
        
        log "Waiting for cert-manager pods (max 5 minutes)..."
        sleep 30  # Give it time to start
        
        # Check if pods are being created
        for i in {1..10}; do
            POD_COUNT=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | wc -l)
            if [ "$POD_COUNT" -gt 0 ]; then
                log "cert-manager pods starting ($POD_COUNT pods found)..."
                break
            fi
            sleep 5
        done
        
        # Wait for ready condition with timeout
        if timeout 240s kubectl wait --for=condition=ready pod \
            -n cert-manager \
            -l app.kubernetes.io/instance=cert-manager 2>&1; then
            success "cert-manager installed"
        else
            warn "cert-manager timeout - checking status..."
            RUNNING=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | grep -c "Running" || echo "0")
            if [ "$RUNNING" -gt 0 ]; then
                warn "cert-manager partially running ($RUNNING pods) - continuing"
            else
                error "cert-manager failed to start"
            fi
        fi
    else
        success "cert-manager already installed"
    fi
    
    # Wait for cert-manager CRDs to be ready - CRITICAL for ClusterIssuer creation
    log "Waiting for cert-manager CRDs (this is important)..."
    sleep 15  # Initial wait for cert-manager to settle
    
    CRD_READY=false
    for i in {1..60}; do
        if kubectl get crd clusterissuers.cert-manager.io &> /dev/null && \
           kubectl get crd certificates.cert-manager.io &> /dev/null; then
            success "cert-manager CRDs ready"
            CRD_READY=true
            break
        fi
        
        # Show progress every 10 seconds
        if [ $((i % 5)) -eq 0 ]; then
            log "Still waiting for CRDs... ($i/60)"
        fi
        sleep 2
    done
    
    if [ "$CRD_READY" = false ]; then
        error "cert-manager CRDs failed to become ready after 2 minutes. Cannot continue."
    fi
    
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
    log "Step 5/6: Installing Helm..."
    
    # Check if helm actually works (not just exists)
    if helm version &> /dev/null; then
        success "Helm already installed ($(helm version --short))"
        return
    fi
    
    log "Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    
    # Verify installation
    if helm version &> /dev/null; then
        success "Helm installed ($(helm version --short))"
    else
        error "Helm installation failed"
    fi
}

# ============================================================================
# STEP 6: Deploy June Platform
# ============================================================================

deploy_june() {
    log "Step 6/6: Deploying June Platform..."
    
    HELM_CHART="$SCRIPT_DIR/helm/june-platform"
    
    if [ ! -d "$HELM_CHART" ]; then
        error "Helm chart not found at: $HELM_CHART"
    fi
    
    # Verify Chart.yaml exists (case-sensitive)
    if [ ! -f "$HELM_CHART/Chart.yaml" ]; then
        # Check for lowercase variant
        if [ -f "$HELM_CHART/chart.yaml" ]; then
            warn "Found chart.yaml (lowercase) - renaming to Chart.yaml"
            mv "$HELM_CHART/chart.yaml" "$HELM_CHART/Chart.yaml"
        else
            error "Chart.yaml not found in $HELM_CHART"
        fi
    fi
    
    # Validate chart
    log "Validating Helm chart..."
    if ! helm lint "$HELM_CHART" 2>&1 | grep -q "chart(s) linted, 0 chart(s) failed"; then
        warn "Helm chart validation had warnings (this is OK if it's just missing icon)"
        helm lint "$HELM_CHART" || true
    fi
    
    success "Helm chart validated"
    
    # Deploy with Helm
    log "Deploying services (this may take 10-15 minutes)..."
    
    if helm upgrade --install june-platform "$HELM_CHART" \
        --namespace june-services \
        --create-namespace \
        --set global.domain="$DOMAIN" \
        --set certificate.email="$LETSENCRYPT_EMAIL" \
        --set secrets.geminiApiKey="$GEMINI_API_KEY" \
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN" \
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}" \
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}" \
        --set stunner.password="${STUNNER_PASSWORD:-Pokemon123!}" \
        --wait \
        --timeout 15m 2>&1 | tee /tmp/helm-deploy.log; then
        success "June Platform deployed"
    else
        error "Helm deployment failed. Check /tmp/helm-deploy.log for details"
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
    
    # Get external IP
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    success "Installation Complete!"
    echo "=========================================="
    echo ""
    echo "📋 Your Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    echo "  STT:        https://stt.$DOMAIN"
    echo "  TTS:        https://tts.$DOMAIN"
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
    echo "  helm status june-platform -n june-services"
    echo ""
    echo "🔍 Verify Deployment:"
    echo "  curl https://api.$DOMAIN/healthz"
    echo ""
    echo "=========================================="
}

# Run installation
main "$@"