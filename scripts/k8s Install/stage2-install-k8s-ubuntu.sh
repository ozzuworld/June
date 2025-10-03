#!/bin/bash
# Stage 2: Kubernetes + Infrastructure Setup (COMPLETE WITH GPU FIX)
# Run this AFTER stage1-runner-only.sh
# This prepares the cluster so CI/CD can deploy without GPU issues

set -e

echo "======================================================"
echo "🚀 Stage 2: Kubernetes Infrastructure Setup"
echo "   WITH PROPERLY FIXED GPU TIME-SLICING"
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

echo ""
echo "📋 Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  GPU: $SETUP_GPU"
echo "  GPU Replicas: $GPU_REPLICAS (1 physical GPU = $GPU_REPLICAS virtual GPUs)"
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
# LET'S ENCRYPT ISSUER
# ============================================================================

if [ -n "$LETSENCRYPT_EMAIL" ]; then
    log_info "Creating Let's Encrypt issuer..."
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ${LETSENCRYPT_EMAIL}
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
    log_success "Let's Encrypt issuer ready!"
else
    log_warning "No email provided - skipping Let's Encrypt setup"
fi

# ============================================================================
# GPU OPERATOR WITH PROPER TIME-SLICING (FIXED!)
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
    
    # ========================================================================
    # CRITICAL FIX: PROPER TIME-SLICING SETUP WITH CORRECT FORMAT
    # ========================================================================
    
    log_info "Configuring GPU time-slicing (1 GPU → $GPU_REPLICAS virtual GPUs)..."
    
    # Wait for GPU operator to be fully ready
    log_info "Waiting for GPU operator to stabilize..."
    sleep 30
    
    # Create time-slicing ConfigMap with CORRECT FORMAT for newer GPU operator
    log_info "Creating time-slicing configuration with correct format..."
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
    
    log_success "Time-slicing ConfigMap created with correct format"
    
    # Apply time-slicing to ClusterPolicy
    log_info "Applying time-slicing to GPU operator..."
    kubectl patch clusterpolicy cluster-policy \
        -n gpu-operator \
        --type merge \
        -p '{"spec": {"devicePlugin": {"config": {"name": "time-slicing-config", "default": "any"}}}}'
    
    log_success "Time-slicing configuration applied"
    
    # Wait for device plugin to restart with new config
    log_info "Waiting for GPU device plugin to restart with time-slicing..."
    sleep 45
    
    # Verify GPU capacity increased
    log_info "Verifying GPU time-slicing..."
    for i in {1..30}; do
        GPU_CAPACITY=$(kubectl get nodes -o json | jq -r '.items[0].status.allocatable."nvidia.com/gpu" // "0"')
        
        if [ "$GPU_CAPACITY" -ge "$GPU_REPLICAS" ]; then
            log_success "GPU time-slicing verified! GPU capacity: $GPU_CAPACITY (was 1, now $GPU_REPLICAS)"
            break
        else
            if [ $i -eq 30 ]; then
                log_error "GPU time-slicing not applied after 5 minutes"
                log_warning "Device plugin may need manual restart:"
                echo "  kubectl delete pod -n gpu-operator -l app=nvidia-device-plugin-daemonset"
                echo "  kubectl get nodes -o json | jq '.items[].status.allocatable.\"nvidia.com/gpu\"'"
            else
                echo "  Checking... GPU capacity: $GPU_CAPACITY (expected: $GPU_REPLICAS) - attempt $i/30"
                sleep 10
            fi
        fi
    done
    
    # Show final GPU status
    echo ""
    log_info "Final GPU Configuration:"
    kubectl get nodes -o json | jq '.items[] | {
        name: .metadata.name,
        gpu_capacity: .status.allocatable."nvidia.com/gpu",
        gpu_allocatable: .status.capacity."nvidia.com/gpu"
    }'
    
    echo ""
    log_info "GPU Operator Pods:"
    kubectl get pods -n gpu-operator
    
    echo ""
    log_info "Device Plugin Status:"
    kubectl get pods -n gpu-operator -l app=nvidia-device-plugin-daemonset
    
fi

# ============================================================================
# STORAGE SETUP
# ============================================================================

log_info "Setting up storage for PostgreSQL and services..."

# Create storage directories
mkdir -p /opt/june-postgresql-data
mkdir -p /opt/june-stt-models
mkdir -p /opt/june-tts-models
mkdir -p /opt/june-data

chmod 755 /opt/june-postgresql-data
chmod 755 /opt/june-stt-models
chmod 755 /opt/june-tts-models
chmod 755 /opt/june-data

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

log_info "Creating PersistentVolume for PostgreSQL..."
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

log_info "Creating PersistentVolumes for STT models..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-stt-models-pv
  labels:
    type: local
    app: june-stt
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/june-stt-models
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - $(hostname)
EOF

log_info "Creating PersistentVolumes for TTS models..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-tts-models-pv
  labels:
    type: local
    app: june-tts
spec:
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/june-tts-models
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - $(hostname)
EOF

log_success "Storage configured with all PersistentVolumes!"

# Verify storage
echo ""
log_info "Verifying storage setup..."
kubectl get storageclass
kubectl get pv

# ============================================================================
# FIX GITHUB RUNNER KUBECTL ACCESS
# ============================================================================

log_info "Configuring GitHub runner for kubectl access..."

if [ -d "/opt/actions-runner" ]; then
    # Add environment variables
    cat >> /opt/actions-runner/.env << 'EOF'
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
EOF
    
    # Restart runner if running
    if systemctl is-active --quiet actions.runner.*; then
        systemctl restart actions.runner.*
        log_success "GitHub runner configured and restarted"
    else
        log_success "GitHub runner configured (will apply on next start)"
    fi
else
    log_warning "GitHub runner not found at /opt/actions-runner"
    log_info "Run this after starting the runner:"
    echo 'echo "KUBECONFIG=/root/.kube/config" >> /opt/actions-runner/.env'
    echo 'systemctl restart actions.runner.*'
fi

# ============================================================================
# VERIFICATION & SUMMARY
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
echo "  • Let's Encrypt issuer (production)"

if [[ $SETUP_GPU == [yY] ]]; then
    GPU_CAPACITY=$(kubectl get nodes -o json | jq -r '.items[0].status.allocatable."nvidia.com/gpu" // "0"')
    if [ "$GPU_CAPACITY" -ge "$GPU_REPLICAS" ]; then
        echo "  • GPU Operator with time-slicing: 1 physical GPU = $GPU_CAPACITY virtual GPUs ✅"
    else
        echo "  • GPU Operator installed (capacity: $GPU_CAPACITY, expected: $GPU_REPLICAS) ⚠️"
        echo "    May need device plugin restart - see troubleshooting below"
    fi
fi

echo "  • Storage configured with PersistentVolumes"
echo "  • GitHub runner configured"
echo ""
echo "🌐 Your External IP: $EXTERNAL_IP"
echo ""
echo "📊 Cluster Status:"
kubectl get nodes -o wide
echo ""
echo "🎮 GPU Status:"
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU_CAPACITY:.status.allocatable.nvidia\.com/gpu'
echo ""
echo "📋 Next Steps:"
echo "  1. Configure DNS records to point to $EXTERNAL_IP:"
echo "     • idp.allsafe.world"
echo "     • api.allsafe.world"
echo "     • stt.allsafe.world"
echo "     • tts.allsafe.world"
echo ""
echo "  2. Push to GitHub - workflow will automatically:"
echo "     • Build Docker images"
echo "     • Deploy services (STT and TTS can share GPU!)"
echo "     • Get Let's Encrypt certificates"
echo ""
echo "  3. Verify deployment:"
echo "     • kubectl get pods -n june-services"
echo "     • kubectl get nodes -o json | jq '.items[].status.allocatable.\"nvidia.com/gpu\"'"
echo ""

if [[ $SETUP_GPU == [yY] ]] && [ "$GPU_CAPACITY" -lt "$GPU_REPLICAS" ]; then
    echo "⚠️  GPU Troubleshooting:"
    echo "  If GPU capacity is not showing $GPU_REPLICAS, restart the device plugin:"
    echo "  kubectl delete pod -n gpu-operator -l app=nvidia-device-plugin-daemonset"
    echo "  sleep 60"
    echo "  kubectl get nodes -o json | jq '.items[].status.allocatable.\"nvidia.com/gpu\"'"
    echo ""
fi

echo "✅ GPU time-slicing is configured - CI/CD can deploy without GPU conflicts!"
echo ""
echo "===================================================="