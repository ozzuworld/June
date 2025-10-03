#!/bin/bash
# Stage 2: Kubernetes + Infrastructure Setup (WITH WILDCARD CERT SUPPORT)
# Run this AFTER stage1-runner-only.sh
# This prepares the cluster so CI/CD can deploy without GPU issues

set -e

echo "======================================================"
echo "🚀 Stage 2: Kubernetes Infrastructure Setup"
echo "   WITH WILDCARD CERTIFICATES & GPU TIME-SLICING"
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

log_info "Configuration"
prompt "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"
prompt "Setup GPU Operator? (y/n)" SETUP_GPU "y"
prompt "GPU time-slicing replicas (2-8)" GPU_REPLICAS "2"
echo ""
log_warning "⚠️  IMPORTANT: Let's Encrypt Rate Limits"
echo "  - Production: 5 certs per domain set per week"
echo "  - Staging: Unlimited (but shows as untrusted)"
echo "  - Use STAGING for testing, switch to PRODUCTION when stable"
echo ""
prompt "Use Let's Encrypt STAGING or PRODUCTION? (staging/production)" CERT_ENV "staging"
prompt "Let's Encrypt email" LETSENCRYPT_EMAIL ""

# NEW: Wildcard certificate option
echo ""
log_info "🌟 WILDCARD CERTIFICATE OPTION"
echo "  ✅ Wildcard (*.allsafe.world) = UNLIMITED subdomains, NO rate limits"
echo "  ✅ Individual domains = Rate limits apply (5 per week max)"
echo ""
prompt "Enable wildcard certificate? (y/n)" ENABLE_WILDCARD "y"

if [[ $ENABLE_WILDCARD == [yY] ]]; then
    echo ""
    log_info "📋 Cloudflare API Token Required:"
    echo "  1. Go to: https://dash.cloudflare.com/profile/api-tokens"
    echo "  2. Create Token > Edit Zone DNS template"
    echo "  3. Permissions: Zone:DNS:Edit, Zone:Zone:Read"
    echo "  4. Zone Resources: allsafe.world"
    echo ""
    prompt "Cloudflare API Token for allsafe.world" CF_API_TOKEN ""
    
    if [ -z "$CF_API_TOKEN" ]; then
        log_error "Cloudflare API token required for wildcard certificates!"
        exit 1
    fi
fi

# Set the correct ACME server based on choice
if [[ $CERT_ENV == "production" ]]; then
    ACME_SERVER="https://acme-v02.api.letsencrypt.org/directory"
    ISSUER_NAME="letsencrypt-prod"
    log_warning "⚠️  Using PRODUCTION - counts against rate limits!"
else
    ACME_SERVER="https://acme-staging-v02.api.letsencrypt.org/directory"
    ISSUER_NAME="letsencrypt-staging"
    log_success "✅ Using STAGING - unlimited testing, certs show as untrusted"
fi

echo ""
echo "📋 Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  GPU: $SETUP_GPU"
echo "  GPU Replicas: $GPU_REPLICAS"
echo "  Certificate Environment: $CERT_ENV"
echo "  Wildcard Enabled: $ENABLE_WILDCARD"
echo "  Issuer Name: $ISSUER_NAME"
echo "  Email: $LETSENCRYPT_EMAIL"
echo ""

read -p "Continue? (y/n): " confirm
[[ $confirm != [yY] ]] && { echo "Cancelled."; exit 0; }

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

# Configure containerd
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

# Install K8s components
rm -f /etc/apt/sources.list.d/kubernetes.list
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Initialize cluster
log_info "Initializing Kubernetes..."
INTERNAL_IP=$(hostname -I | awk '{print $1}')
kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock

# Setup kubeconfig
mkdir -p /root/.kube
cp /etc/kubernetes/admin.conf /root/.kube/config
chown root:root /root/.kube/config

# Install Flannel
log_info "Installing Flannel..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Untaint node
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for ready
log_info "Waiting for cluster..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes ready!"

# ============================================================================
# INGRESS-NGINX (hostNetwork for VM)
# ============================================================================

log_info "Installing ingress-nginx..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml

sleep 15

log_info "Enabling hostNetwork (direct port 80/443 access)..."
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
# LET'S ENCRYPT ISSUER (WITH WILDCARD SUPPORT)
# ============================================================================

if [ -n "$LETSENCRYPT_EMAIL" ]; then
    log_info "Creating Let's Encrypt issuer ($CERT_ENV)..."
    
    if [[ $CERT_ENV == "staging" ]]; then
        log_warning "📝 Note: Staging certificates will show as UNTRUSTED in browsers"
        log_info "This is NORMAL for testing - switch to production when ready"
    else
        log_warning "⚠️  Using PRODUCTION - you have 5 attempts per week per domain set!"
    fi
    
    if [[ $ENABLE_WILDCARD == [yY] ]] && [ -n "$CF_API_TOKEN" ]; then
        log_info "Creating Cloudflare API secret..."
        kubectl create secret generic cloudflare-api-token \
            --from-literal=api-token="$CF_API_TOKEN" \
            --namespace=cert-manager \
            --dry-run=client -o yaml | kubectl apply -f -
        
        log_info "Creating DNS-01 ClusterIssuer for wildcard certificates..."
        cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: ${ISSUER_NAME}
spec:
  acme:
    server: ${ACME_SERVER}
    email: ${LETSENCRYPT_EMAIL}
    privateKeySecretRef:
      name: ${ISSUER_NAME}
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsNames:
        - "allsafe.world"
        - "*.allsafe.world"
EOF
        
        log_success "Wildcard ClusterIssuer '${ISSUER_NAME}' created with DNS-01!"
        echo ""
        log_info "🌟 Wildcard Benefits:"
        echo "  • *.allsafe.world covers ALL current and future subdomains"
        echo "  • No more rate limit concerns for new services"
        echo "  • Perfect for your 'nuke daily' workflow"
        
    else
        log_info "Creating HTTP-01 ClusterIssuer for individual certificates..."
        cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: ${ISSUER_NAME}
spec:
  acme:
    server: ${ACME_SERVER}
    email: ${LETSENCRYPT_EMAIL}
    privateKeySecretRef:
      name: ${ISSUER_NAME}
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
        
        log_success "Standard ClusterIssuer '${ISSUER_NAME}' created with HTTP-01!"
    fi
    
else
    log_warning "No email provided - skipping Let's Encrypt setup"
fi

# ============================================================================
# GPU OPERATOR WITH PROPER TIME-SLICING
# ============================================================================

if [[ $SETUP_GPU == [yY] ]]; then
    log_info "Installing GPU Operator with time-slicing..."
    
    # Install Helm
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
    
    # GPU Time-slicing setup
    log_info "Configuring GPU time-slicing (1 GPU → $GPU_REPLICAS virtual GPUs)..."
    
    sleep 30
    
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
    
    kubectl patch clusterpolicy cluster-policy \
        -n gpu-operator \
        --type merge \
        -p '{"spec": {"devicePlugin": {"config": {"name": "time-slicing-config", "default": "any"}}}}'
    
    log_success "GPU time-slicing configured!"
    
fi

# ============================================================================
# STORAGE SETUP
# ============================================================================

log_info "Setting up storage..."

mkdir -p /opt/june-postgresql-data
mkdir -p /opt/june-stt-models
mkdir -p /opt/june-tts-models
mkdir -p /opt/june-data

chmod 755 /opt/june-*

cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

# Create all PVs
for service in postgresql june-stt-models june-tts-models; do
    size="10Gi"
    if [ "$service" == "june-tts-models" ]; then
        size="20Gi"
    fi
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ${service}-pv
  labels:
    type: local
    app: ${service}
spec:
  capacity:
    storage: ${size}
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/${service/june-/june-}
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - $(hostname)
EOF
done

log_success "Storage configured!"

# ============================================================================
# GITHUB RUNNER SETUP
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
        log_success "GitHub runner configured (will apply on next start)"
    fi
else
    log_warning "GitHub runner not found - configure manually later"
fi

# ============================================================================
# FINAL STATUS
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ || hostname -I | awk '{print $1}')

echo ""
echo "🎉======================================================"
log_success "Stage 2 Complete!"
echo "======================================================"
echo ""
echo "✅ Infrastructure Ready:"
echo "  • Kubernetes cluster"
echo "  • ingress-nginx (hostNetwork mode)"
echo "  • cert-manager"

if [[ $ENABLE_WILDCARD == [yY] ]]; then
    echo "  • Let's Encrypt issuer: $ISSUER_NAME (WILDCARD enabled)"
    echo "  • DNS-01 challenge with Cloudflare"
else
    echo "  • Let's Encrypt issuer: $ISSUER_NAME (individual domains)"
    echo "  • HTTP-01 challenge"
fi

if [[ $SETUP_GPU == [yY] ]]; then
    echo "  • GPU Operator with time-slicing ($GPU_REPLICAS virtual GPUs)"
fi

echo "  • Storage configured"
echo "  • GitHub runner ready"
echo ""
echo "🌐 External IP: $EXTERNAL_IP"
echo ""
echo "📋 Next Steps:"
echo ""
echo "  1. Configure DNS to point to $EXTERNAL_IP:"

if [[ $ENABLE_WILDCARD == [yY] ]]; then
    echo "     • *.allsafe.world (wildcard record)"
    echo "     • allsafe.world (root domain)"
else
    echo "     • api.allsafe.world"
    echo "     • idp.allsafe.world"
    echo "     • stt.allsafe.world"
    echo "     • tts.allsafe.world"
fi

echo ""
echo "  2. Apply ingress configuration:"
echo "     kubectl apply -f scripts/k8s Install/k8s-ingress-complete.yaml"
echo ""
echo "  3. Push to GitHub to trigger deployment"
echo ""

if [[ $CERT_ENV == "staging" ]]; then
    echo "💡 Note: Using STAGING certificates (will show as untrusted)"
    echo "   This is PERFECT for testing. Switch to production when stable."
    echo ""
fi

if [[ $ENABLE_WILDCARD == [yY] ]]; then
    echo "🌟 Wildcard Benefits:"
    echo "   • One certificate covers unlimited subdomains"
    echo "   • No rate limit concerns"
    echo "   • Perfect for frequent deployments"
    echo ""
fi

echo "✅ Ready for deployment!"
echo "===================================================="
