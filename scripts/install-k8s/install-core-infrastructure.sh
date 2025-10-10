#!/bin/bash
# Core Infrastructure Setup: K8s + Docker + ingress-nginx + cert-manager
# This is the foundation - run this first
# Usage: ./install-core-infrastructure.sh

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
echo "🏗️  Core Infrastructure Setup"
echo "   Docker + Kubernetes + Ingress + Cert-Manager"
echo "======================================================"
echo ""

# Configuration
CONFIG_DIR="/root/.june-config"
mkdir -p "$CONFIG_DIR"

# ============================================================================
# CONFIGURATION COLLECTION (MOVED TO TOP)
# ============================================================================

log_info "📋 Loading/Collecting Configuration..."

# Load existing configs if available
if [ -f "$CONFIG_DIR/infrastructure.env" ]; then
    log_info "Loading infrastructure config..."
    source "$CONFIG_DIR/infrastructure.env"
fi

if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    log_info "Loading domain config..."
    source "$CONFIG_DIR/domain-config.env"
fi

# Collect missing infrastructure configuration
if [ -z "$POD_NETWORK_CIDR" ] || [ -z "$LETSENCRYPT_EMAIL" ] || [ -z "$CF_API_TOKEN" ]; then
    log_info "Collecting infrastructure configuration..."
    
    read -p "Pod network CIDR [10.244.0.0/16]: " POD_NETWORK_CIDR
    POD_NETWORK_CIDR=${POD_NETWORK_CIDR:-10.244.0.0/16}
    
    read -p "Let's Encrypt email: " LETSENCRYPT_EMAIL
    read -p "Cloudflare API Token: " CF_API_TOKEN
    
    # Save configuration
cat > "$CONFIG_DIR/infrastructure.env" << EOF
POD_NETWORK_CIDR=$POD_NETWORK_CIDR
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
CF_API_TOKEN=$CF_API_TOKEN
INSTALL_DATE="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
EOF
    chmod 600 "$CONFIG_DIR/infrastructure.env"
    log_success "Infrastructure config saved"
fi

# Collect missing domain configuration
if [ -z "$PRIMARY_DOMAIN" ]; then
    log_info "Collecting domain configuration..."
    
    read -p "Primary domain [ozzu.world]: " PRIMARY_DOMAIN
    PRIMARY_DOMAIN=${PRIMARY_DOMAIN:-ozzu.world}
    
    read -p "API subdomain [api]: " API_SUBDOMAIN
    API_SUBDOMAIN=${API_SUBDOMAIN:-api}
    
    read -p "IDP subdomain [idp]: " IDP_SUBDOMAIN
    IDP_SUBDOMAIN=${IDP_SUBDOMAIN:-idp}
    
    read -p "STT subdomain [stt]: " STT_SUBDOMAIN
    STT_SUBDOMAIN=${STT_SUBDOMAIN:-stt}
    
    read -p "TTS subdomain [tts]: " TTS_SUBDOMAIN
    TTS_SUBDOMAIN=${TTS_SUBDOMAIN:-tts}
    
    # Construct full domains
    API_DOMAIN="${API_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    IDP_DOMAIN="${IDP_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    STT_DOMAIN="${STT_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    TTS_DOMAIN="${TTS_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"
    CERT_NAME="${PRIMARY_DOMAIN//./-}-wildcard"
    CERT_SECRET_NAME="${CERT_NAME}-tls"
    
    # Save domain config
cat > "$CONFIG_DIR/domain-config.env" << EOF
PRIMARY_DOMAIN=$PRIMARY_DOMAIN
API_DOMAIN=$API_DOMAIN
IDP_DOMAIN=$IDP_DOMAIN
STT_DOMAIN=$STT_DOMAIN
TTS_DOMAIN=$TTS_DOMAIN
WILDCARD_DOMAIN=$WILDCARD_DOMAIN
CERT_NAME=$CERT_NAME
CERT_SECRET_NAME=$CERT_SECRET_NAME
EOF
    chmod 600 "$CONFIG_DIR/domain-config.env"
    log_success "Domain config saved"
else
    # Recalculate cert names if not set
    if [ -z "$CERT_SECRET_NAME" ]; then
        CERT_NAME="${PRIMARY_DOMAIN//./-}-wildcard"
        CERT_SECRET_NAME="${CERT_NAME}-tls"
        echo "CERT_NAME=$CERT_NAME" >> "$CONFIG_DIR/domain-config.env"
        echo "CERT_SECRET_NAME=$CERT_SECRET_NAME" >> "$CONFIG_DIR/domain-config.env"
    fi
    log_success "Configuration loaded"
fi

# Display summary
echo ""
log_info "Configuration:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  Domain: $PRIMARY_DOMAIN"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo "  Email: $LETSENCRYPT_EMAIL"
echo ""

# ============================================================================
# DOCKER
# ============================================================================

log_info "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io
else
    log_success "Docker already installed"
fi

# Configure containerd
systemctl stop containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

log_success "Docker configured!"

# ============================================================================
# KUBERNETES
# ============================================================================

log_info "☸️  Installing Kubernetes..."

# Kernel modules
modprobe br_netfilter
cat <<EOF | tee /etc/modules-load.d/k8s.conf
br_netfilter
EOF

cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

# Install K8s packages
if ! command -v kubeadm &> /dev/null; then
    rm -f /etc/apt/sources.list.d/kubernetes.list
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl
    apt-mark hold kubelet kubeadm kubectl
else
    log_success "Kubernetes packages already installed"
fi

# Initialize cluster if not already done
if [ ! -f /etc/kubernetes/admin.conf ]; then
    log_info "Initializing Kubernetes cluster..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock
    
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
else
    log_success "Kubernetes already initialized"
fi

# Install Flannel
log_info "Installing Flannel network..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove taints
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes cluster ready!"

# ============================================================================
# INGRESS-NGINX
# ============================================================================

log_info "🌐 Installing ingress-nginx..."
if ! kubectl get namespace ingress-nginx &>/dev/null; then
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml
    sleep 15
    
    # Enable hostNetwork
    log_info "Enabling hostNetwork mode..."
    kubectl patch deployment ingress-nginx-controller \
        -n ingress-nginx \
        --type='json' \
        -p='[
            {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
            {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
        ]'
    
    # Wait for rollout
    log_info "Waiting for ingress controller rollout..."
    kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s
else
    log_success "ingress-nginx already installed"
fi

# Verify
log_info "Verifying ingress controller..."
kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=120s 2>/dev/null || {
    log_warning "Wait timed out, checking status..."
    kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller
}

log_success "ingress-nginx ready!"

# ============================================================================
# CERT-MANAGER
# ============================================================================

log_info "🔐 Installing cert-manager..."
if ! kubectl get namespace cert-manager &>/dev/null; then
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml
    kubectl create namespace cert-manager
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml
    
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/instance=cert-manager \
        -n cert-manager \
        --timeout=180s
else
    log_success "cert-manager already installed"
fi

# Create Cloudflare secret
kubectl create secret generic cloudflare-api-token \
    --from-literal=api-token="$CF_API_TOKEN" \
    --namespace=cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "cert-manager ready!"

# ============================================================================
# CERTIFICATE MANAGEMENT (RESTORE OR CREATE)
# ============================================================================

log_info "🔐 Certificate Management: Checking for backup..."

CERT_BACKUP_DIR="/root/.june-certs"
CERT_RESTORED=false

kubectl create namespace june-services || true

if [ -d "$CERT_BACKUP_DIR" ]; then
    CERT_BACKUP=$(find "$CERT_BACKUP_DIR" -name "*wildcard-tls-backup.yaml" -type f | head -1)
    
    if [ -n "$CERT_BACKUP" ] && [ -f "$CERT_BACKUP" ]; then
        log_info "Found certificate backup: $CERT_BACKUP"
        
        if grep -q "kind: Secret" "$CERT_BACKUP" && grep -q "tls.crt" "$CERT_BACKUP"; then
            log_success "Backup file is valid"
            
            kubectl apply -f "$CERT_BACKUP"
            
            BACKUP_SECRET_NAME=$(grep -A1 "kind: Secret" "$CERT_BACKUP" | grep "name:" | head -1 | awk '{print $2}')
            sleep 2
            
            if kubectl get secret "$BACKUP_SECRET_NAME" -n june-services &>/dev/null; then
                log_success "Certificate restored from backup: $BACKUP_SECRET_NAME"
                
                EXPIRY=$(kubectl get secret "$BACKUP_SECRET_NAME" -n june-services -o jsonpath='{.data.tls\.crt}' | \
                         base64 -d | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
                
                if [ -n "$EXPIRY" ]; then
                    log_info "Certificate expires: $EXPIRY"
                    
                    EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null)
                    NOW_EPOCH=$(date +%s)
                    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
                    
                    if [ $DAYS_LEFT -lt 0 ]; then
                        log_error "Certificate has EXPIRED! Creating new one..."
                        kubectl delete secret "$BACKUP_SECRET_NAME" -n june-services
                        CERT_RESTORED=false
                    elif [ $DAYS_LEFT -lt 30 ]; then
                        log_warning "Certificate expires in $DAYS_LEFT days"
                        CERT_RESTORED=true
                        CERT_SECRET_NAME="$BACKUP_SECRET_NAME"
                        sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$CERT_SECRET_NAME/" "$CONFIG_DIR/domain-config.env" || true
                    else
                        log_success "Certificate is valid ($DAYS_LEFT days remaining)"
                        CERT_RESTORED=true
                        CERT_SECRET_NAME="$BACKUP_SECRET_NAME"
                        sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$CERT_SECRET_NAME/" "$CONFIG_DIR/domain-config.env" || true
                    fi
                else
                    log_warning "Could not check expiration, assuming valid"
                    CERT_RESTORED=true
                    CERT_SECRET_NAME="$BACKUP_SECRET_NAME"
                    sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$CERT_SECRET_NAME/" "$CONFIG_DIR/domain-config.env" || true
                fi
            else
                log_error "Certificate restoration failed"
                CERT_RESTORED=false
            fi
        else
            log_error "Backup file is invalid or corrupted"
            CERT_RESTORED=false
        fi
    else
        log_info "No certificate backup found"
    fi
else
    log_info "Certificate backup directory does not exist (first-time setup)"
fi

# If no valid backup, create Certificate resource
if [ "$CERT_RESTORED" = false ]; then
    log_info "🔐 Creating Certificate resource for cert-manager..."
    
    # Verify PRIMARY_DOMAIN is set
    if [ -z "$PRIMARY_DOMAIN" ]; then
        log_error "PRIMARY_DOMAIN is not set! Cannot create certificate."
        exit 1
    fi
    
    log_info "Using domain: $PRIMARY_DOMAIN"
    log_info "Certificate name: $CERT_NAME"
    log_info "Secret name: $CERT_SECRET_NAME"
    
    # Create ClusterIssuers first
    log_info "Creating ClusterIssuers..."
    
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
        - "${PRIMARY_DOMAIN}"
        - "*.${PRIMARY_DOMAIN}"
EOF
    
    log_success "ClusterIssuer created"
    
    # Create Certificate
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ${CERT_NAME}
  namespace: june-services
spec:
  secretName: ${CERT_SECRET_NAME}
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: "${PRIMARY_DOMAIN}"
  dnsNames:
  - "${PRIMARY_DOMAIN}"
  - "*.${PRIMARY_DOMAIN}"
EOF
    
    log_success "Certificate resource created"
    log_warning "⏳ Waiting for cert-manager to issue certificate (2-5 minutes)..."
    
    for i in {1..60}; do
        CERT_READY=$(kubectl get certificate "${CERT_NAME}" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
        
        if [ "$CERT_READY" = "True" ]; then
            log_success "Certificate issued successfully!"
            break
        fi
        
        if [ $((i % 10)) -eq 0 ]; then
            log_info "Still waiting for certificate... (${i}/60)"
        fi
        
        sleep 5
    done
    
    if [ "$CERT_READY" = "True" ]; then
        log_success "Certificate is ready to use"
        log_warning "💾 IMPORTANT: Run after deployment:"
        log_warning "   ./scripts/install-k8s/backup-wildcard-cert.sh"
    else
        log_error "Certificate issuance timed out"
        log_error "Check: kubectl describe certificate ${CERT_NAME} -n june-services"
    fi
fi

log_success "Certificate management complete!"
log_success "Using certificate secret: ${CERT_SECRET_NAME}"

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
done

# Create StorageClass
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

# Create PostgreSQL PV
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
          - $(hostname)
EOF

log_success "Storage infrastructure ready!"

# ============================================================================
# SUMMARY
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ || hostname -I | awk '{print $1}')

echo ""
echo "======================================================"
log_success "Core Infrastructure Ready!"
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
echo "🌍 Cluster Info:"
echo "  External IP: $EXTERNAL_IP"
echo "  Domain: $PRIMARY_DOMAIN"
echo "  Certificate: $CERT_SECRET_NAME"
echo "  Namespace: june-services"
echo ""
echo "📝 Next Steps:"
echo "  1. Install MetalLB + STUNner:"
echo "     ./install-networking.sh"
echo ""
echo "  2. Install GPU Operator (optional):"
echo "     ./install-gpu-operator.sh"
echo ""
echo "  3. Deploy June services:"
echo "     kubectl apply -f k8s/complete-manifests.yaml"
echo ""
echo "======================================================"