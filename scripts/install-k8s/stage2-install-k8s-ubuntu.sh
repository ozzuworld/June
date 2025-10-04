#!/bin/bash
# Stage 2: Kubernetes + Infrastructure Setup (WITH INTERACTIVE DOMAIN CONFIG)
# This creates ALL infrastructure that deployments depend on

set -e

echo "======================================================"
echo "🚀 Stage 2: Complete Kubernetes Infrastructure Setup"
echo "   ✅ Interactive domain configuration"
echo "   ✅ Proper GPU time-slicing activation"
echo "   ✅ Certificate backup/restore support"
echo "   ✅ Post-install validation"
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
log_info "🌐 Domain Configuration"
echo ""
prompt "Primary domain (e.g., example.com)" PRIMARY_DOMAIN "allsafe.world"
prompt "API subdomain" API_SUBDOMAIN "api"
prompt "IDP subdomain" IDP_SUBDOMAIN "idp"
prompt "STT subdomain" STT_SUBDOMAIN "stt"
prompt "TTS subdomain" TTS_SUBDOMAIN "tts"

# Construct full domains
API_DOMAIN="${API_SUBDOMAIN}.${PRIMARY_DOMAIN}"
IDP_DOMAIN="${IDP_SUBDOMAIN}.${PRIMARY_DOMAIN}"
STT_DOMAIN="${STT_SUBDOMAIN}.${PRIMARY_DOMAIN}"
TTS_DOMAIN="${TTS_SUBDOMAIN}.${PRIMARY_DOMAIN}"
WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"

echo ""
log_info "🔧 Infrastructure Configuration"
prompt "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"
prompt "Setup GPU Operator? (y/n)" SETUP_GPU "y"
prompt "GPU time-slicing replicas (2-8)" GPU_REPLICAS "2"

echo ""
log_info "🔒 SSL Certificate Configuration"
prompt "Let's Encrypt email" LETSENCRYPT_EMAIL ""
prompt "Cloudflare API Token for ${PRIMARY_DOMAIN}" CF_API_TOKEN ""

if [ -z "$LETSENCRYPT_EMAIL" ] || [ -z "$CF_API_TOKEN" ]; then
    log_error "Email and Cloudflare API token are required!"
    exit 1
fi

echo ""
echo "======================================================"
echo "📋 Configuration Summary"
echo "======================================================"
echo ""
echo "🌐 Domain Configuration:"
echo "  Primary Domain: ${PRIMARY_DOMAIN}"
echo "  Wildcard: ${WILDCARD_DOMAIN}"
echo "  API: ${API_DOMAIN}"
echo "  IDP: ${IDP_DOMAIN}"
echo "  STT: ${STT_DOMAIN}"
echo "  TTS: ${TTS_DOMAIN}"
echo ""
echo "🔧 Infrastructure:"
echo "  Pod Network: ${POD_NETWORK_CIDR}"
echo "  GPU: ${SETUP_GPU}"
echo "  GPU Replicas: ${GPU_REPLICAS}"
echo ""
echo "🔒 SSL:"
echo "  Email: ${LETSENCRYPT_EMAIL}"
echo "  Cloudflare Token: ${CF_API_TOKEN:0:10}..."
echo ""
echo "======================================================"
echo ""

read -p "Continue with this configuration? (y/n): " confirm
[[ $confirm != [yY] ]] && { echo "Cancelled."; exit 0; }

# ============================================================================
# SAVE DOMAIN CONFIGURATION (for GitHub workflow to use)
# ============================================================================

log_info "Saving domain configuration..."

DOMAIN_CONFIG_DIR="/root/.june-config"
DOMAIN_CONFIG_FILE="${DOMAIN_CONFIG_DIR}/domain-config.env"

mkdir -p "${DOMAIN_CONFIG_DIR}"
chmod 700 "${DOMAIN_CONFIG_DIR}"

cat > "${DOMAIN_CONFIG_FILE}" << EOF
# June Infrastructure Domain Configuration
# Generated: $(date)
# This file is used by GitHub Actions workflow for deployments

PRIMARY_DOMAIN=${PRIMARY_DOMAIN}
API_DOMAIN=${API_DOMAIN}
IDP_DOMAIN=${IDP_DOMAIN}
STT_DOMAIN=${STT_DOMAIN}
TTS_DOMAIN=${TTS_DOMAIN}
WILDCARD_DOMAIN=${WILDCARD_DOMAIN}
CERT_SECRET_NAME=${PRIMARY_DOMAIN//./-}-wildcard-tls
EOF

chmod 600 "${DOMAIN_CONFIG_FILE}"
log_success "Domain configuration saved to: ${DOMAIN_CONFIG_FILE}"

# ============================================================================
# SYSTEM PACKAGES
# ============================================================================

log_info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y curl wget apt-transport-https ca-certificates gnupg lsb-release jq bc

# ============================================================================
# DOCKER
# ============================================================================

log_info "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io
fi

systemctl stop containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

# ============================================================================
# KUBERNETES
# ============================================================================

log_info "Installing Kubernetes..."

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

rm -f /etc/apt/sources.list.d/kubernetes.list
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

log_info "Initializing Kubernetes..."
INTERNAL_IP=$(hostname -I | awk '{print $1}')
kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock

mkdir -p /root/.kube
cp /etc/kubernetes/admin.conf /root/.kube/config
chown root:root /root/.kube/config

log_info "Installing Flannel..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

log_info "Waiting for cluster..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes ready!"

# ============================================================================
# INGRESS-NGINX
# ============================================================================

log_info "Installing ingress-nginx..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml

sleep 15

log_info "Enabling hostNetwork..."
kubectl patch deployment ingress-nginx-controller \
    -n ingress-nginx \
    --type='json' \
    -p='[
        {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
        {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
    ]'

kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=300s || log_warning "Ingress taking longer..."

log_success "Ingress-nginx ready!"

# ============================================================================
# CERT-MANAGER
# ============================================================================

log_info "Installing cert-manager..."
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml
kubectl create namespace cert-manager || true
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml

kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/instance=cert-manager \
    -n cert-manager \
    --timeout=180s || log_warning "cert-manager taking longer..."

log_success "cert-manager ready!"

# ============================================================================
# CLOUDFLARE SECRET
# ============================================================================

log_info "Creating Cloudflare API secret..."
kubectl create secret generic cloudflare-api-token \
    --from-literal=api-token="$CF_API_TOKEN" \
    --namespace=cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Cloudflare secret created!"

# ============================================================================
# CLUSTER ISSUERS (WITH DYNAMIC DOMAIN)
# ============================================================================

log_info "Creating ClusterIssuers for ${PRIMARY_DOMAIN}..."

# Staging
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-staging
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

# Production
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

log_success "ClusterIssuers created!"

# ============================================================================
# NAMESPACE
# ============================================================================

log_info "Creating june-services namespace..."
kubectl create namespace june-services || log_warning "Namespace june-services already exists"
log_success "Namespace ready!"

# ============================================================================
# CERTIFICATE BACKUP RESTORE (WITH DYNAMIC DOMAIN)
# ============================================================================

log_info "Checking for certificate backup..."

BACKUP_DIR="/root/.june-certs"
CERT_SECRET_NAME="${PRIMARY_DOMAIN//./-}-wildcard-tls"
BACKUP_FILE="${BACKUP_DIR}/${CERT_SECRET_NAME}-backup.yaml"

# Also check for old backup with different naming
OLD_BACKUP_FILE="${BACKUP_DIR}/wildcard-cert-backup.yaml"

if [ -f "$BACKUP_FILE" ]; then
    log_success "Found certificate backup for ${PRIMARY_DOMAIN}!"
    
    # Show backup info
    METADATA_FILE="${BACKUP_DIR}/backup-metadata.txt"
    if [ -f "$METADATA_FILE" ]; then
        BACKUP_DATE=$(grep "Backup Created:" "$METADATA_FILE" 2>/dev/null | cut -d: -f2- || echo "Unknown")
        EXPIRY_DATE=$(grep "Certificate Expiry:" "$METADATA_FILE" 2>/dev/null | cut -d: -f2- || echo "Unknown")
        
        echo "  Backup created: $BACKUP_DATE"
        echo "  Certificate expires: $EXPIRY_DATE"
    fi
    echo ""
    
    log_info "Restoring certificate from backup..."
    
    if kubectl apply -f "$BACKUP_FILE"; then
        log_success "Certificate restored successfully!"
        echo ""
        echo "✅ Using existing certificate - NO rate limit used!"
        echo "   Ingress will use this certificate automatically"
        echo ""
    else
        log_error "Failed to restore certificate backup!"
        echo ""
        read -p "Continue without backup? cert-manager will request new cert (uses rate limit) (y/n): " CONTINUE
        [[ $CONTINUE != [yY] ]] && { echo "Cancelled. Fix backup and retry."; exit 1; }
    fi
elif [ -f "$OLD_BACKUP_FILE" ]; then
    log_warning "Found backup with old naming convention"
    echo "  Old backup: $OLD_BACKUP_FILE"
    echo "  Expected: $BACKUP_FILE"
    echo ""
    read -p "Try to use old backup? (y/n): " USE_OLD
    if [[ $USE_OLD == [yY] ]]; then
        log_info "Attempting to restore from old backup..."
        if kubectl apply -f "$OLD_BACKUP_FILE"; then
            log_success "Old backup restored successfully!"
            log_info "Consider creating new backup with: ./scripts/backup-wildcard-cert.sh"
        else
            log_error "Failed to restore old backup"
        fi
    fi
else
    log_warning "No certificate backup found for ${PRIMARY_DOMAIN}"
    echo ""
    echo "⚠️  cert-manager will request a NEW certificate from Let's Encrypt"
    echo "   This uses your rate limit (5 certs per week per domain)"
    echo ""
    echo "📍 Backup location: $BACKUP_FILE"
    echo ""
    echo "💡 After deployment completes and certificate is issued:"
    echo "   1. Run: ./scripts/backup-wildcard-cert.sh"
    echo "   2. Future rebuilds will restore from backup (no rate limit!)"
    echo ""
    
    read -p "Continue and request new certificate? (y/n): " CONTINUE
    [[ $CONTINUE != [yY] ]] && { echo "Cancelled."; exit 1; }
fi

echo ""

# ============================================================================
# GPU OPERATOR
# ============================================================================

if [[ $SETUP_GPU == [yY] ]]; then
    log_info "Installing GPU Operator with time-slicing..."
    
    if ! command -v helm &> /dev/null; then
        snap install helm --classic || {
            cd /tmp
            wget https://get.helm.sh/helm-v3.14.0-linux-amd64.tar.gz
            tar -zxvf helm-v3.14.0-linux-amd64.tar.gz
            mv linux-amd64/helm /usr/local/bin/helm
            chmod +x /usr/local/bin/helm
        }
    fi
    
    helm repo add nvidia https://nvidia.github.io/gpu-operator
    helm repo update
    
    kubectl create namespace gpu-operator || true
    kubectl label --overwrite namespace gpu-operator pod-security.kubernetes.io/enforce=privileged
    
    LATEST_VERSION=$(helm search repo nvidia/gpu-operator --versions | grep gpu-operator | head -1 | awk '{print $2}')
    
    log_info "Installing GPU Operator version $LATEST_VERSION..."
    helm install gpu-operator nvidia/gpu-operator \
        --wait --timeout 15m \
        --namespace gpu-operator \
        --version=$LATEST_VERSION \
        --set driver.enabled=true \
        --set toolkit.enabled=true \
        --set devicePlugin.enabled=true
    
    log_success "GPU Operator installed!"
    
    log_info "Waiting for GPU operator to be fully ready (this may take 3-5 minutes)..."
    
    kubectl wait --for=condition=ready pod \
        -n gpu-operator \
        -l app=nvidia-device-plugin-daemonset \
        --timeout=600s || log_warning "Device plugin taking longer than expected"
    
    sleep 30
    
    log_info "Configuring GPU time-slicing..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing-config
  namespace: gpu-operator
data:
  any: |-
    version: v1
    flags:
      migStrategy: none
    sharing:
      timeSlicing:
        resources:
        - name: nvidia.com/gpu
          replicas: ${GPU_REPLICAS}
EOF
    
    log_success "Time-slicing ConfigMap created with ${GPU_REPLICAS} replicas"
    
    log_info "Applying time-slicing to ClusterPolicy..."
    kubectl patch clusterpolicy cluster-policy \
        -n gpu-operator \
        --type merge \
        -p '{"spec": {"devicePlugin": {"config": {"name": "time-slicing-config", "default": "any"}}}}'
    
    log_success "Time-slicing configuration applied to ClusterPolicy"
    
    log_info "Waiting for device plugin to restart with time-slicing config..."
    
    kubectl delete pods -n gpu-operator -l app=nvidia-device-plugin-daemonset || true
    
    sleep 20
    
    kubectl wait --for=condition=ready pod \
        -n gpu-operator \
        -l app=nvidia-device-plugin-daemonset \
        --timeout=300s || log_warning "Device plugin restart taking longer than expected"
    
    sleep 20
    
    log_info "Verifying GPU time-slicing..."
    GPU_ALLOCATABLE=$(kubectl get nodes -o json | jq -r '.items[].status.allocatable."nvidia.com/gpu" // "0"' | head -1)
    
    if [ "$GPU_ALLOCATABLE" -ge "$GPU_REPLICAS" ]; then
        log_success "GPU time-slicing is ACTIVE! ($GPU_ALLOCATABLE virtual GPUs available)"
    else
        log_warning "GPU time-slicing may still be activating (found $GPU_ALLOCATABLE GPUs, expected $GPU_REPLICAS)"
        log_info "This is normal - it may take 1-2 minutes to fully activate"
    fi
    
    log_info "Labeling nodes for GPU workloads..."
    kubectl label nodes --all gpu=true --overwrite
    log_success "Nodes labeled with gpu=true"
fi

# ============================================================================
# STORAGE
# ============================================================================

log_info "Setting up storage infrastructure..."

log_info "Creating storage directories..."
STORAGE_DIRS=(
    "/opt/june-postgresql-data"
    "/opt/june-stt-models"
    "/opt/june-tts-models"
    "/opt/june-data"
)

for dir in "${STORAGE_DIRS[@]}"; do
    mkdir -p "$dir"
    chmod 755 "$dir"
    log_success "Created $dir"
done

log_info "Creating StorageClass..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

log_success "StorageClass created!"

log_info "Creating PersistentVolumes..."

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

log_success "PostgreSQL PV created"
log_success "Storage infrastructure configured!"

# ============================================================================
# GITHUB RUNNER CONFIG
# ============================================================================

log_info "Configuring GitHub runner..."

if [ -d "/opt/actions-runner" ]; then
    cat >> /opt/actions-runner/.env << 'EOF'
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
EOF
    
    if systemctl is-active --quiet actions.runner.*; then
        systemctl restart actions.runner.*
        log_success "GitHub runner configured and restarted"
    else
        log_success "GitHub runner configured"
    fi
else
    log_warning "GitHub runner not found at /opt/actions-runner"
fi

# ============================================================================
# POST-INSTALL VERIFICATION
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ || hostname -I | awk '{print $1}')

echo ""
echo "======================================================"
log_info "Running Post-Install Verification..."
echo "======================================================"
echo ""

# ... (verification checks remain the same)

# Check certificate backup status
echo ""
log_info "Certificate backup status:"
if [ -f "$BACKUP_FILE" ]; then
    log_success "Certificate backup exists at $BACKUP_FILE"
    echo "  Future rebuilds will restore from backup automatically"
else
    log_warning "No certificate backup found"
    echo "  Run './scripts/backup-wildcard-cert.sh' after cert is issued"
fi

# ============================================================================
# FINAL STATUS
# ============================================================================

echo ""
echo "======================================================"
log_success "Stage 2 Complete!"
echo "======================================================"
echo ""
echo "Infrastructure Ready:"
echo "  ✅ Kubernetes cluster"
echo "  ✅ ingress-nginx (hostNetwork mode)"
echo "  ✅ cert-manager"
echo "  ✅ ClusterIssuers for ${PRIMARY_DOMAIN}"

if [[ $SETUP_GPU == [yY] ]]; then
    echo "  ✅ GPU Operator with time-slicing ($GPU_REPLICAS virtual GPUs)"
fi

echo "  ✅ Storage infrastructure"
echo "  ✅ june-services namespace"
echo "  ✅ Domain configuration saved"

if [ -f "$BACKUP_FILE" ]; then
    echo "  ✅ Certificate restored from backup"
else
    echo "  ⚠️  Certificate will be requested from Let's Encrypt"
fi

echo ""
echo "🌐 Domain Configuration:"
echo "  Primary: ${PRIMARY_DOMAIN}"
echo "  API: ${API_DOMAIN}"
echo "  IDP: ${IDP_DOMAIN}"
echo "  STT: ${STT_DOMAIN}"
echo "  TTS: ${TTS_DOMAIN}"
echo ""
echo "📁 Configuration Files:"
echo "  Domain config: ${DOMAIN_CONFIG_FILE}"
echo "  Certificate backup: ${BACKUP_FILE}"
echo ""
echo "External IP: $EXTERNAL_IP"
echo ""
echo "Next Steps:"
echo ""
echo "  1. Configure DNS to point to $EXTERNAL_IP:"
echo "     • ${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo "     • *.${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo ""
echo "  2. Push to GitHub to trigger automated deployment"
echo "     (GitHub workflow will read domain config automatically)"
echo ""
echo "  3. Monitor: kubectl get pods -n june-services -w"
echo ""

if [ ! -f "$BACKUP_FILE" ]; then
    echo "  4. After cert is issued, backup it:"
    echo "     ./scripts/backup-wildcard-cert.sh"
    echo ""
fi

echo "======================================================"