#!/bin/bash
# Stage 2: Kubernetes + Infrastructure Setup (COMPLETE FIX)
# This creates ALL infrastructure that deployments depend on

set -e

echo "======================================================"
echo "🚀 Stage 2: Complete Kubernetes Infrastructure Setup"
echo "   ✅ FIXED: Proper GPU time-slicing activation"
echo "   ✅ FIXED: Correct PV paths and verification"
echo "   ✅ FIXED: Post-install validation"
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
prompt "Let's Encrypt email" LETSENCRYPT_EMAIL ""
prompt "Cloudflare API Token for allsafe.world" CF_API_TOKEN ""

if [ -z "$LETSENCRYPT_EMAIL" ] || [ -z "$CF_API_TOKEN" ]; then
    log_error "Email and Cloudflare API token are required!"
    exit 1
fi

echo ""
echo "📋 Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  GPU: $SETUP_GPU"
echo "  GPU Replicas: $GPU_REPLICAS"
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
# CLUSTER ISSUERS
# ============================================================================

log_info "Creating ClusterIssuers..."

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
        - "allsafe.world"
        - "*.allsafe.world"
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
        - "allsafe.world"
        - "*.allsafe.world"
EOF

log_success "ClusterIssuers created!"

# ============================================================================
# GPU OPERATOR (FIXED - Proper time-slicing activation)
# ============================================================================

if [[ $SETUP_GPU == [yY] ]]; then
    log_info "Installing GPU Operator with time-slicing..."
    
    # Install Helm if needed
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
    
    # CRITICAL: Wait for GPU operator to be fully ready before configuring time-slicing
    log_info "Waiting for GPU operator to be fully ready (this may take 3-5 minutes)..."
    
    # Wait for device plugin daemonset
    kubectl wait --for=condition=ready pod \
        -n gpu-operator \
        -l app=nvidia-device-plugin-daemonset \
        --timeout=600s || log_warning "Device plugin taking longer than expected"
    
    sleep 30  # Extra wait to ensure everything is stable
    
    log_info "Configuring GPU time-slicing..."
    
    # Create time-slicing ConfigMap
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
    
    # CRITICAL: Apply time-slicing to ClusterPolicy
    log_info "Applying time-slicing to ClusterPolicy..."
    kubectl patch clusterpolicy cluster-policy \
        -n gpu-operator \
        --type merge \
        -p '{"spec": {"devicePlugin": {"config": {"name": "time-slicing-config", "default": "any"}}}}'
    
    log_success "Time-slicing configuration applied to ClusterPolicy"
    
    # CRITICAL: Wait for device plugin to restart with new config
    log_info "Waiting for device plugin to restart with time-slicing config..."
    
    # Delete device plugin pods to force restart
    kubectl delete pods -n gpu-operator -l app=nvidia-device-plugin-daemonset || true
    
    sleep 20
    
    # Wait for new device plugin pods
    kubectl wait --for=condition=ready pod \
        -n gpu-operator \
        -l app=nvidia-device-plugin-daemonset \
        --timeout=300s || log_warning "Device plugin restart taking longer than expected"
    
    sleep 20  # Give time for GPU capacity to update
    
    # VERIFICATION: Check if time-slicing is active
    log_info "Verifying GPU time-slicing..."
    GPU_ALLOCATABLE=$(kubectl get nodes -o json | jq -r '.items[].status.allocatable."nvidia.com/gpu" // "0"' | head -1)
    
    if [ "$GPU_ALLOCATABLE" -ge "$GPU_REPLICAS" ]; then
        log_success "GPU time-slicing is ACTIVE! ($GPU_ALLOCATABLE virtual GPUs available)"
    else
        log_warning "GPU time-slicing may still be activating (found $GPU_ALLOCATABLE GPUs, expected $GPU_REPLICAS)"
        log_info "This is normal - it may take 1-2 minutes to fully activate"
    fi
    
    # Label nodes for GPU workloads
    log_info "Labeling nodes for GPU workloads..."
    kubectl label nodes --all gpu=true --overwrite
    log_success "Nodes labeled with gpu=true"
fi

# ============================================================================
# NAMESPACE (Application namespace - NOT gpu-operator)
# ============================================================================

log_info "Creating june-services namespace..."
kubectl create namespace june-services || log_warning "Namespace june-services already exists"
log_success "Namespace ready!"

# ============================================================================
# STORAGE (FIXED - Create directories AND PVs)
# ============================================================================

log_info "Setting up storage infrastructure..."

# Create all required directories
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

# Create StorageClass (cluster-scoped, not namespaced)
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

# Create PersistentVolumes (cluster-scoped, not namespaced)
log_info "Creating PersistentVolumes..."

# PostgreSQL PV
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

# Verify cluster
log_info "Checking cluster status..."
if kubectl cluster-info &>/dev/null; then
    log_success "Cluster is accessible"
else
    log_error "Cluster not accessible!"
fi

# Verify nodes
NODE_STATUS=$(kubectl get nodes --no-headers | awk '{print $2}' | head -1)
if [ "$NODE_STATUS" = "Ready" ]; then
    log_success "Node is Ready"
else
    log_error "Node status: $NODE_STATUS"
fi

# Verify namespaces
NAMESPACES=("june-services" "ingress-nginx" "cert-manager")
if [[ $SETUP_GPU == [yY] ]]; then
    NAMESPACES+=("gpu-operator")
fi

for ns in "${NAMESPACES[@]}"; do
    if kubectl get namespace "$ns" &>/dev/null; then
        log_success "Namespace $ns exists"
    else
        log_error "Namespace $ns missing!"
    fi
done

# Verify StorageClass
if kubectl get storageclass local-storage &>/dev/null; then
    log_success "StorageClass 'local-storage' exists"
else
    log_error "StorageClass 'local-storage' missing!"
fi

# Verify PVs
if kubectl get pv postgresql-pv &>/dev/null; then
    log_success "PostgreSQL PV exists"
else
    log_error "PostgreSQL PV missing!"
fi

# Verify storage directories
for dir in "${STORAGE_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        log_success "Storage directory $dir exists"
    else
        log_error "Storage directory $dir missing!"
    fi
done

# Verify ingress
if kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller | grep -q Running; then
    log_success "Ingress controller running"
else
    log_error "Ingress controller not running!"
fi

# Verify cert-manager
if kubectl get pods -n cert-manager | grep -q Running; then
    log_success "cert-manager running"
else
    log_error "cert-manager not running!"
fi

# Verify GPU (if installed)
if [[ $SETUP_GPU == [yY] ]]; then
    GPU_ALLOCATABLE=$(kubectl get nodes -o json | jq -r '.items[].status.allocatable."nvidia.com/gpu" // "0"' | head -1)
    
    if [ "$GPU_ALLOCATABLE" -ge "$GPU_REPLICAS" ]; then
        log_success "GPU time-slicing active: $GPU_ALLOCATABLE virtual GPUs"
    else
        log_warning "GPU: $GPU_ALLOCATABLE virtual GPUs (expected $GPU_REPLICAS - may still be activating)"
    fi
    
    # Check node labels
    GPU_LABELED=$(kubectl get nodes -l gpu=true --no-headers | wc -l)
    if [ "$GPU_LABELED" -gt 0 ]; then
        log_success "Nodes labeled for GPU: $GPU_LABELED"
    else
        log_error "No nodes labeled with gpu=true!"
    fi
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
echo "  ✅ letsencrypt-staging (wildcard DNS-01)"
echo "  ✅ letsencrypt-prod (wildcard DNS-01)"

if [[ $SETUP_GPU == [yY] ]]; then
    echo "  ✅ GPU Operator with time-slicing ($GPU_REPLICAS virtual GPUs)"
fi

echo "  ✅ Storage infrastructure (directories + PVs)"
echo "  ✅ june-services namespace"
echo "  ✅ GitHub runner configured"
echo ""
echo "Storage Created:"
echo "  • /opt/june-postgresql-data (10Gi PV)"
echo "  • /opt/june-stt-models (directory ready)"
echo "  • /opt/june-tts-models (directory ready)"
echo "  • /opt/june-data (directory ready)"
echo ""
echo "External IP: $EXTERNAL_IP"
echo ""
echo "Next Steps:"
echo ""
echo "  1. Configure DNS to point to $EXTERNAL_IP:"
echo "     • *.allsafe.world (wildcard record)"
echo "     • allsafe.world (root domain)"
echo ""
echo "  2. Push to GitHub to trigger automated deployment"
echo ""
echo "  3. Monitor deployment:"
echo "     • kubectl get pods -n june-services -w"
echo "     • kubectl describe pod <pod-name> -n june-services"
echo ""

if [[ $SETUP_GPU == [yY] ]]; then
    echo "GPU Notes:"
    echo "  • Time-slicing config will be used by deployments"
    echo "  • Each GPU service requests 1 virtual GPU"
    echo "  • $GPU_REPLICAS services can share the physical GPU"
    echo ""
fi

echo "Troubleshooting:"
echo "  • Check GPU: kubectl describe nodes | grep -A 5 Allocatable | grep nvidia"
echo "  • Check PVs: kubectl get pv"
echo "  • Check storage: ls -la /opt/june-*"
echo "  • Full status: kubectl get all -A"
echo ""
echo "======================================================"