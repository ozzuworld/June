#!/bin/bash
# Simplified June Platform Infrastructure Setup
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
echo "🏗️  June Platform Infrastructure Setup"
echo "======================================================"
echo ""

# Load configuration
if [ -f ".env" ]; then
    source .env
    log_success "Loaded configuration from .env"
else
    log_error ".env file not found. Please create it with your domain configuration."
    echo ""
    echo "Required variables in .env:"
    echo "  PRIMARY_DOMAIN=yourdomain.com"
    echo "  LETSENCRYPT_EMAIL=you@yourdomain.com"
    echo "  CF_API_TOKEN=your-cloudflare-token"
    echo "  POD_NETWORK_CIDR=10.244.0.0/16"
    echo "  POSTGRES_PASSWORD=your-postgres-password"
    echo "  KEYCLOAK_ADMIN_PASSWORD=your-keycloak-password"
    echo "  GEMINI_API_KEY=your-gemini-key"
    exit 1
fi

# Validate required variables
REQUIRED_VARS=("PRIMARY_DOMAIN" "LETSENCRYPT_EMAIL" "CF_API_TOKEN")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        log_error "Required variable $var is not set in .env"
        exit 1
    fi
done

# Set defaults for optional variables
POD_NETWORK_CIDR=${POD_NETWORK_CIDR:-10.244.0.0/16}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-Pokemon123!}
KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}

log_info "Configuration Summary:"
echo "  Domain: $PRIMARY_DOMAIN"
echo "  Email: $LETSENCRYPT_EMAIL"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo ""

# ============================================================================
# DOCKER INSTALLATION
# ============================================================================

log_info "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    log_info "Installing Docker CE..."
    
    # Update package index
    apt-get update -qq
    
    # Install dependencies
    apt-get install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    # Add Docker GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    
    # Add Docker repository
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io
    
    log_success "Docker installed successfully"
else
    log_success "Docker already installed"
fi

# Configure containerd for Kubernetes
log_info "Configuring containerd..."
systemctl stop containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml

# Enable SystemdCgroup
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Restart and enable containerd
systemctl restart containerd
systemctl enable containerd

log_success "Docker and containerd configured!"

# ============================================================================
# KUBERNETES INSTALLATION
# ============================================================================

log_info "☸️  Installing Kubernetes..."

# Load kernel modules
log_info "Loading required kernel modules..."
modprobe br_netfilter

cat <<EOF | tee /etc/modules-load.d/k8s.conf
br_netfilter
EOF

# Set sysctl parameters
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

# Install Kubernetes packages
if ! command -v kubeadm &> /dev/null; then
    log_info "Installing Kubernetes packages..."
    
    # Remove old sources
    rm -f /etc/apt/sources.list.d/kubernetes.list
    
    # Add Kubernetes GPG key
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    # Add Kubernetes repository
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
    
    # Install packages
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl
    apt-mark hold kubelet kubeadm kubectl
    
    log_success "Kubernetes packages installed"
else
    log_success "Kubernetes packages already installed"
fi

# Initialize Kubernetes cluster
if [ ! -f /etc/kubernetes/admin.conf ]; then
    log_info "🚀 Initializing Kubernetes cluster..."
    
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    log_info "Using internal IP: $INTERNAL_IP"
    
    kubeadm init \
        --pod-network-cidr=$POD_NETWORK_CIDR \
        --apiserver-advertise-address=$INTERNAL_IP \
        --cri-socket=unix:///var/run/containerd/containerd.sock
    
    # Set up kubectl for root
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    log_success "Kubernetes cluster initialized"
else
    log_success "Kubernetes cluster already initialized"
fi

# Install Flannel network plugin
log_info "🌐 Installing Flannel network plugin..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove taints to allow scheduling on control plane
log_info "Removing control plane taints..."
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster to be ready
log_info "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes cluster is ready!"

# ============================================================================
# INGRESS-NGINX INSTALLATION
# ============================================================================

log_info "🌐 Installing ingress-nginx..."
if ! kubectl get namespace ingress-nginx &>/dev/null; then
    log_info "Deploying ingress-nginx controller..."
    
    # Install ingress-nginx
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml
    
    # Wait for initial deployment
    sleep 15
    
    # Enable hostNetwork mode for bare metal
    log_info "Enabling hostNetwork mode..."
    kubectl patch deployment ingress-nginx-controller \
        -n ingress-nginx \
        --type='json' \
        -p='[
            {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
            {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
        ]'
    
    # Wait for rollout to complete
    log_info "⏳ Waiting for ingress controller rollout..."
    kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s
    
    log_success "ingress-nginx deployed successfully"
else
    log_success "ingress-nginx already installed"
fi

# Verify ingress controller is ready
log_info "🔍 Verifying ingress controller..."
kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=120s || {
    log_warning "Wait timed out, checking status..."
    kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller
}

log_success "ingress-nginx is ready!"

# ============================================================================
# CERT-MANAGER INSTALLATION
# ============================================================================

log_info "🔐 Installing cert-manager..."
if ! kubectl get namespace cert-manager &>/dev/null; then
    log_info "Installing cert-manager CRDs..."
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml
    
    log_info "Creating cert-manager namespace..."
    kubectl create namespace cert-manager
    
    log_info "Installing cert-manager..."
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml
    
    log_info "⏳ Waiting for cert-manager to be ready..."
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/instance=cert-manager \
        -n cert-manager \
        --timeout=180s
    
    log_success "cert-manager installed successfully"
else
    log_success "cert-manager already installed"
fi

# Verify cert-manager components are ready
log_info "🔍 Verifying cert-manager readiness..."
kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=60s
kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=60s
kubectl wait --for=condition=Available deployment/cert-manager-cainjector -n cert-manager --timeout=60s

# Create Cloudflare API token secret
log_info "🌩️  Creating Cloudflare API token secret..."
kubectl create secret generic cloudflare-api-token \
    --from-literal=api-token="$CF_API_TOKEN" \
    --namespace=cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "cert-manager is ready!"

# ============================================================================
# CERTIFICATE ISSUER SETUP
# ============================================================================

log_info "📜 Creating Let's Encrypt ClusterIssuer..."

cat <<EOF | kubectl apply -f -
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
        - "$PRIMARY_DOMAIN"
        - "*.$PRIMARY_DOMAIN"
EOF

# Wait for ClusterIssuer to be ready
log_info "⏳ Waiting for ClusterIssuer to be ready..."
sleep 10

# Verify ClusterIssuer status
for i in {1..30}; do
    ISSUER_READY=$(kubectl get clusterissuer letsencrypt-prod -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
    if [ "$ISSUER_READY" = "True" ]; then
        log_success "ClusterIssuer is ready"
        break
    fi
    
    if [ $i -eq 30 ]; then
        log_warning "ClusterIssuer not ready yet, but proceeding..."
    fi
    
    sleep 2
done

# ============================================================================
# STORAGE SETUP
# ============================================================================

log_info "📁 Setting up storage infrastructure..."

# Create storage directories
STORAGE_DIRS=(
    "/opt/june-postgresql-data"
    "/opt/june-data"
)

for dir in "${STORAGE_DIRS[@]}"; do
    mkdir -p "$dir"
    chmod 755 "$dir"
    log_info "Created directory: $dir"
done

# Create StorageClass
log_info "Creating local StorageClass..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

# Create PostgreSQL PersistentVolume
log_info "Creating PostgreSQL PersistentVolume..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgresql-pv
  labels:
    type: local
    app: postgresql
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/june-postgresql-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - "$(hostname)"
EOF

log_success "Storage infrastructure ready!"

# ============================================================================
# FINAL VALIDATION AND SUMMARY
# ============================================================================

# Get external IP
EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')

# Generate derived domain names for display
API_DOMAIN="api.${PRIMARY_DOMAIN}"
IDP_DOMAIN="idp.${PRIMARY_DOMAIN}"
STT_DOMAIN="stt.${PRIMARY_DOMAIN}"
TTS_DOMAIN="tts.${PRIMARY_DOMAIN}"
CERT_NAME="${PRIMARY_DOMAIN//./-}-wildcard"
CERT_SECRET_NAME="${CERT_NAME}-tls"

echo ""
echo "======================================================"
log_success "🎉 Infrastructure Installation Complete!"
echo "======================================================"
echo ""
echo "✅ Installed Components:"
echo "  • Docker + containerd"
echo "  • Kubernetes 1.28 cluster"
echo "  • Flannel networking ($POD_NETWORK_CIDR)"
echo "  • ingress-nginx (hostNetwork mode)"
echo "  • cert-manager with Cloudflare DNS"
echo "  • Local storage infrastructure"
echo ""
echo "🌍 Cluster Configuration:"
echo "  External IP: $EXTERNAL_IP"
echo "  Primary Domain: $PRIMARY_DOMAIN"
echo "  Certificate Name: $CERT_NAME"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo ""
echo "🔗 Service Endpoints (after deployment):"
echo "  API: https://$API_DOMAIN"
echo "  Identity Provider: https://$IDP_DOMAIN"
echo "  Speech-to-Text: https://$STT_DOMAIN"
echo "  Text-to-Speech: https://$TTS_DOMAIN"
echo ""
echo "📝 Next Steps:"
echo "  1. Generate manifests for your domain:"
echo "     ./scripts/generate-manifests.sh"
echo ""
echo "  2. Deploy June services:"
echo "     kubectl apply -f k8s/june-manifests.yaml"
echo ""
echo "  3. Monitor certificate issuance:"
echo "     kubectl get certificates -n june-services"
echo ""
echo "  4. Backup certificates once issued:"
echo "     ./scripts/backup-cert.sh"
echo ""
echo "🔧 Configuration Files:"
echo "  Domain config: .env"
echo "  Generated manifests: k8s/june-manifests.yaml"
echo "  Certificate backups: /root/cert-backups/"
echo ""
echo "🔍 Useful Commands:"
echo "  kubectl get pods -n june-services"
echo "  kubectl get ingress -n june-services"
echo "  kubectl describe certificate $CERT_NAME -n june-services"
echo ""
echo "======================================================"

log_success "🚀 Ready to deploy June Platform!"
