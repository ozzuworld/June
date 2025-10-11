#!/bin/bash
# June Platform - Unified Installation Script
# One script to install everything: K8s + Helm + June Platform + STUNner
# With automatic certificate backup/restore to avoid Let's Encrypt rate limits

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
SKIP_CERT_CREATION="false"

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

install_prerequisites() {
    log "Step 1/8: Installing prerequisites..."
    
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
    log "Step 2/8: Installing Docker..."
    
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
    log "Step 3/8: Installing Kubernetes..."
    
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
    log "Step 4/8: Installing infrastructure components..."
    
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
# STEP 4.5: Restore Certificate Backup
# ============================================================================

restore_certificate_if_exists() {
    log "Step 4.5/8: Checking for certificate backup..."
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_info "No backup directory found, will create new certificate"
        return
    fi
    
    LATEST_BACKUP=$(find "$BACKUP_DIR" -name "${CERT_SECRET_NAME}*.yaml" -o -name "*wildcard*.yaml" 2>/dev/null | head -1)
    
    if [ -z "$LATEST_BACKUP" ]; then
        log_info "No certificate backups found, will create new certificate"
        return
    fi
    
    log_info "Found certificate backup: $(basename "$LATEST_BACKUP")"
    
    if ! grep -q "tls.crt" "$LATEST_BACKUP" || ! grep -q "tls.key" "$LATEST_BACKUP"; then
        warn "Backup file appears invalid"
        return
    fi
    
    CERT_BASE64=$(grep "tls.crt:" "$LATEST_BACKUP" | sed 's/.*tls.crt: *//' | tr -d ' \n')
    
    if [ -z "$CERT_BASE64" ]; then
        CERT_BASE64=$(awk '/tls.crt:/{flag=1; next} /tls.key:/{flag=0} flag' "$LATEST_BACKUP" | tr -d ' \n')
    fi
    
    if [ -z "$CERT_BASE64" ]; then
        warn "Could not extract certificate data"
        return
    fi
    
    CERT_DATA=$(echo "$CERT_BASE64" | base64 -d 2>/dev/null)
    
    if [ -z "$CERT_DATA" ]; then
        warn "Could not decode certificate data"
        return
    fi
    
    EXPIRY_DATE=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    
    if [ -z "$EXPIRY_DATE" ]; then
        warn "Could not parse certificate expiration"
        return
    fi
    
    EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s 2>/dev/null || echo "0")
    NOW_EPOCH=$(date +%s)
    DAYS_UNTIL_EXPIRY=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))
    
    if [ "$DAYS_UNTIL_EXPIRY" -le 7 ]; then
        warn "Certificate expires in $DAYS_UNTIL_EXPIRY days (too soon)"
        return
    fi
    
    log_info "Certificate valid for $DAYS_UNTIL_EXPIRY more days, restoring..."
    
    kubectl create namespace cert-manager --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    TEMP_CERT_FILE="/tmp/cert-restore-temp.yaml"
    sed 's/namespace: june-services/namespace: cert-manager/g' "$LATEST_BACKUP" > "$TEMP_CERT_FILE"
    
    if kubectl apply -f "$TEMP_CERT_FILE" > /dev/null 2>&1; then
        rm -f "$TEMP_CERT_FILE"
        sleep 3
        
        if kubectl get secret "$CERT_SECRET_NAME" -n cert-manager &>/dev/null; then
            success "Certificate restored to cert-manager namespace"
            SKIP_CERT_CREATION="true"
            log_info "⚡ Avoiding Let's Encrypt rate limit!"
        else
            warn "Certificate restoration verification failed"
        fi
    else
        rm -f "$TEMP_CERT_FILE"
        warn "Failed to apply certificate backup"
    fi
}

# ============================================================================
# STEP 5: Install Gateway API + STUNner
# ============================================================================

install_stunner() {
    log "Step 5/8: Installing Gateway API v1 + STUNner..."
    
    # Install Gateway API v1.3.0 (stable)
    log "Installing Gateway API v1.3.0..."
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml > /dev/null 2>&1
    
    sleep 10
    
    # Wait for Gateway API CRDs
    log "Waiting for Gateway API CRDs..."
    for i in {1..30}; do
        if kubectl get crd gatewayclasses.gateway.networking.k8s.io &>/dev/null && \
           kubectl get crd gateways.gateway.networking.k8s.io &>/dev/null; then
            success "Gateway API CRDs ready"
            break
        fi
        sleep 2
    done
    
    # Install Helm if needed
    if ! command -v helm &> /dev/null; then
        log "Installing Helm..."
        curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    fi
    
    # Add STUNner repo
    log "Adding STUNner Helm repository..."
    helm repo add stunner https://l7mp.io/stunner > /dev/null 2>&1
    helm repo update > /dev/null 2>&1
    
    # Install STUNner operator
    if helm list -n stunner-system 2>/dev/null | grep -q stunner; then
        success "STUNner already installed"
    else
        log "Installing STUNner operator (this creates the dataplane automatically)..."
        
        helm install stunner stunner/stunner \
            --create-namespace \
            --namespace=stunner-system \
            --wait \
            --timeout=10m > /dev/null 2>&1
        
        success "STUNner operator installed"
    fi
    
    # Wait for operator
    log "Waiting for STUNner operator..."
    sleep 20
    
    kubectl wait --for=condition=ready pod \
        -n stunner-system \
        -l control-plane=stunner-gateway-operator-controller-manager \
        --timeout=300s > /dev/null 2>&1 || warn "STUNner operator startup timeout"
    
    # Create stunner namespace for gateway resources
    kubectl create namespace stunner --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Get external IP
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    log_info "External IP: $EXTERNAL_IP"
    
    # Create GatewayConfig with STUNner auth credentials
    log "Creating STUNner GatewayConfig..."
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: stunner.l7mp.io/v1
kind: GatewayConfig
metadata:
  name: stunner-gatewayconfig
  namespace: stunner-system
spec:
  realm: turn.$DOMAIN
  authType: static
  userName: ${TURN_USERNAME:-june-user}
  password: ${STUNNER_PASSWORD:-Pokemon123!}
  logLevel: all:INFO
EOF
    
    # Create GatewayClass
    log "Creating STUNner GatewayClass..."
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
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
  description: "STUNner Gateway for June WebRTC Services"
EOF
    
    # Create Gateway with LoadBalancer
    log "Creating STUNner Gateway..."
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: june-stunner-gateway
  namespace: stunner
  annotations:
    stunner.l7mp.io/service-type: LoadBalancer
spec:
  gatewayClassName: stunner-gatewayclass
  listeners:
  - name: udp-listener
    port: 3478
    protocol: UDP
    allowedRoutes:
      namespaces:
        from: All
  - name: tcp-listener
    port: 3478
    protocol: TCP
    allowedRoutes:
      namespaces:
        from: All
EOF
    
    # Wait for gateway
    log "Waiting for STUNner Gateway..."
    sleep 20
    
    # Create ReferenceGrant for cross-namespace access
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    log "Creating ReferenceGrant..."
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-june-services
  namespace: june-services
spec:
  from:
  - group: stunner.l7mp.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF
    
    success "STUNner installation complete"
}

# ============================================================================
# STEP 6: Install Helm
# ============================================================================

install_helm() {
    log "Step 6/8: Verifying Helm..."
    
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
# STEP 7: Deploy June Platform
# ============================================================================

deploy_june() {
    log "Step 7/8: Deploying June Platform..."
    
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
    
    HELM_ARGS=(
        --namespace june-services
        --create-namespace
        --set global.domain="$DOMAIN"
        --set certificate.email="$LETSENCRYPT_EMAIL"
        --set secrets.geminiApiKey="$GEMINI_API_KEY"
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN"
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}"
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
        --set stunner.enabled=true
        --set stunner.username="${TURN_USERNAME:-june-user}"
        --set stunner.password="${STUNNER_PASSWORD:-Pokemon123!}"
        --wait
        --timeout 15m
    )
    
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        log_info "Using restored certificate"
        HELM_ARGS+=(--set certificate.enabled=false)
        HELM_ARGS+=(--set certificate.secretName="$CERT_SECRET_NAME")
    fi
    
    log "Deploying services..."
    
    set +e
    helm upgrade --install june-platform "$HELM_CHART" "${HELM_ARGS[@]}" 2>&1 | tee /tmp/helm-deploy.log
    HELM_EXIT_CODE=$?
    set -e
    
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
    
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        log_info "Copying certificate to june-services..."
        
        kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o yaml | \
            sed 's/namespace: cert-manager/namespace: june-services/' | \
            kubectl apply -f - > /dev/null 2>&1
    fi
}

# ============================================================================
# STEP 8: Backup New Certificate
# ============================================================================

backup_new_certificate() {
    log "Step 8/8: Certificate backup management..."
    
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        log_info "Using existing certificate backup"
        return
    fi
    
    log_info "Backing up newly created certificate..."
    
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    
    log "Waiting for certificate to be issued..."
    
    for i in {1..60}; do
        if kubectl get secret "$CERT_SECRET_NAME" -n cert-manager &>/dev/null 2>&1; then
            CERT_DATA=$(kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o jsonpath='{.data.tls\.crt}' 2>/dev/null)
            if [ -n "$CERT_DATA" ]; then
                break
            fi
        fi
        sleep 5
    done
    
    BACKUP_FILE="$BACKUP_DIR/${CERT_SECRET_NAME}_$(date +%Y%m%d_%H%M%S).yaml"
    
    kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o yaml > "$BACKUP_FILE"
    
    if [ -f "$BACKUP_FILE" ]; then
        if grep -q "tls.crt" "$BACKUP_FILE" && grep -q "tls.key" "$BACKUP_FILE"; then
            success "Certificate backed up to: $BACKUP_FILE"
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
    restore_certificate_if_exists
    install_stunner
    install_helm
    deploy_june
    backup_new_certificate
    
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
    echo "  TURN:       turn:turn.$DOMAIN:3478"
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
    echo "🎯 STUNner TURN Server:"
    echo "  URL:        turn:turn.$DOMAIN:3478"
    echo "  Username:   ${TURN_USERNAME:-june-user}"
    echo "  Password:   ${STUNNER_PASSWORD:-Pokemon123!}"
    echo ""
    echo "📊 Check Status:"
    echo "  kubectl get pods -n june-services"
    echo "  kubectl get gateway -n stunner"
    echo "  kubectl get pods -n stunner-system"
    echo ""
    echo "=========================================="
}

main "$@"