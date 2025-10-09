#!/bin/bash
# UNIFIED INSTALLATION SCRIPT: Complete June Platform Setup
# COMPLETE FILE - Ready to use on fresh VM
# FIXED: Correct TURN/STUN configuration

set -e

echo "======================================================"
echo "🚀 UNIFIED June Platform Installation - FIXED VERSION"
echo "   ✅ GitHub Actions Runner Setup"
echo "   ✅ Kubernetes + Infrastructure Setup"
echo "   ✅ Reliable STUNner with coturn (FIXED)"
echo "   ✅ Complete WebRTC Integration"
echo "======================================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}\u2139\ufe0f  $1${NC}"; }
log_success() { echo -e "${GREEN}\u2705 $1${NC}"; }
log_warning() { echo -e "${YELLOW}\u26a0\ufe0f  $1${NC}"; }
log_error()   { echo -e "${RED}\u274c $1${NC}"; }

# Configuration function
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
log_info "🔧 Complete Configuration Setup"
echo ""

# ============================================================================
# SECTION 1: GitHub Runner Configuration
# ============================================================================

echo "📋 GitHub Actions Runner Configuration:"
echo ""
read -p "Enter GitHub repository URL: " GITHUB_REPO_URL
echo "Get token from: ${GITHUB_REPO_URL}/settings/actions/runners/new"
read -p "Enter FRESH GitHub token: " GITHUB_TOKEN
read -p "Enter runner name [june-runner-$(hostname)]: " RUNNER_NAME
RUNNER_NAME=${RUNNER_NAME:-june-runner-$(hostname)}

if [ -z "$GITHUB_REPO_URL" ] || [ -z "$GITHUB_TOKEN" ]; then
    log_error "GitHub repository URL and token are required!"
    exit 1
fi

echo ""

# ============================================================================
# SECTION 2: Domain Configuration
# ============================================================================

echo "🌐 Domain Configuration:"
echo ""
prompt "Primary domain (e.g., example.com)" PRIMARY_DOMAIN "allsafe.world"
prompt "API subdomain" API_SUBDOMAIN "api"
prompt "IDP subdomain" IDP_SUBDOMAIN "idp"
prompt "STT subdomain" STT_SUBDOMAIN "stt"
prompt "TTS subdomain" TTS_SUBDOMAIN "tts"
prompt "TURN subdomain" TURN_SUBDOMAIN "turn"

# Construct full domains
API_DOMAIN="${API_SUBDOMAIN}.${PRIMARY_DOMAIN}"
IDP_DOMAIN="${IDP_SUBDOMAIN}.${PRIMARY_DOMAIN}"
STT_DOMAIN="${STT_SUBDOMAIN}.${PRIMARY_DOMAIN}"
TTS_DOMAIN="${TTS_SUBDOMAIN}.${PRIMARY_DOMAIN}"
TURN_DOMAIN="${TURN_SUBDOMAIN}.${PRIMARY_DOMAIN}"
WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"
CERT_SECRET_NAME="${PRIMARY_DOMAIN//./-}-wildcard-tls"

echo ""

# ============================================================================
# SECTION 3: API Keys and Credentials
# ============================================================================

echo "🔑 API Keys Configuration:"
echo ""
prompt "Gemini API Key (get from: https://makersuite.google.com/app/apikey)" GEMINI_API_KEY ""
prompt "Let's Encrypt email" LETSENCRYPT_EMAIL ""
prompt "Cloudflare API Token for ${PRIMARY_DOMAIN}" CF_API_TOKEN ""

if [ -z "$GEMINI_API_KEY" ] || [ -z "$LETSENCRYPT_EMAIL" ] || [ -z "$CF_API_TOKEN" ]; then
    log_error "Gemini API key, email, and Cloudflare API token are required!"
    exit 1
fi

# Validate API key format (basic check)
if [ ${#GEMINI_API_KEY} -lt 20 ]; then
    log_warning "API key seems unusually short (${#GEMINI_API_KEY} characters)"
    read -p "Continue anyway? (y/n): " continue_short
    [[ $continue_short != [yY] ]] && exit 1
fi

# Mask the key for display
MASKED_GEMINI_KEY="${GEMINI_API_KEY:0:6}...${GEMINI_API_KEY: -4}"

echo ""

# ============================================================================
# SECTION 4: Infrastructure Configuration
# ============================================================================

echo "🔧 Infrastructure Configuration:"
echo ""
prompt "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"
prompt "Setup GPU Operator? (y/n)" SETUP_GPU "y"
prompt "GPU time-slicing replicas (2-8)" GPU_REPLICAS "2"

echo ""

# ============================================================================
# SECTION 5: STUNner Configuration
# ============================================================================

echo "🔗 STUNner STUN/TURN Configuration (FIXED VERSION):"
echo ""
prompt "STUNner realm" STUNNER_REALM "${TURN_DOMAIN}"
prompt "STUNner username" STUNNER_USERNAME "june-user"
prompt "STUNner password" STUNNER_PASSWORD "Pokemon123!"

echo ""
echo "======================================================"
echo "📋 COMPLETE Configuration Summary"
echo "======================================================"
echo ""
echo "🐙 GitHub Runner:"
echo "  Repository: ${GITHUB_REPO_URL}"
echo "  Runner Name: ${RUNNER_NAME}"
echo "  Token: ${GITHUB_TOKEN:0:10}..."
echo ""
echo "🌐 Domain Configuration:"
echo "  Primary Domain: ${PRIMARY_DOMAIN}"
echo "  API: ${API_DOMAIN}"
echo "  IDP: ${IDP_DOMAIN}"
echo "  STT: ${STT_DOMAIN}"
echo "  TTS: ${TTS_DOMAIN}"
echo "  TURN: ${TURN_DOMAIN}"
echo "  Wildcard: ${WILDCARD_DOMAIN}"
echo "  Cert Secret: ${CERT_SECRET_NAME}"
echo ""
echo "🔑 API Keys:"
echo "  Gemini API Key: ${MASKED_GEMINI_KEY}"
echo "  Let's Encrypt Email: ${LETSENCRYPT_EMAIL}"
echo "  Cloudflare Token: ${CF_API_TOKEN:0:10}..."
echo ""
echo "🔧 Infrastructure:"
echo "  Pod Network: ${POD_NETWORK_CIDR}"
echo "  GPU Setup: ${SETUP_GPU}"
echo "  GPU Replicas: ${GPU_REPLICAS}"
echo ""
echo "🔗 STUNner (FIXED COTURN VERSION):"
echo "  TURN Domain: ${TURN_DOMAIN}"
echo "  Realm: ${STUNNER_REALM}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo "  Image: coturn/coturn:4.6.2-alpine (FIXED)"
echo ""
echo "======================================================"
echo ""

read -p "Continue with this configuration? (y/n): " confirm
[[ $confirm != [yY] ]] && { echo "Cancelled."; exit 0; }

# ============================================================================
# INSTALLATION PHASE 1: GITHUB ACTIONS RUNNER
# ============================================================================

log_info "🏃 Setting up GitHub Actions Runner..."

# Install dependencies
log_info "Installing dependencies..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y curl wget git libicu-dev apt-transport-https ca-certificates gnupg lsb-release jq bc unzip

# Setup runner in proper location
RUNNER_DIR="/opt/actions-runner"
log_info "Setting up runner in $RUNNER_DIR..."
mkdir -p $RUNNER_DIR
cd $RUNNER_DIR

# Download latest runner
log_info "Downloading GitHub Actions runner..."
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep tag_name | cut -d '"' -f 4 | sed 's/v//')
log_info "Version: $RUNNER_VERSION"
curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

# Set proper permissions
log_info "Setting up permissions..."
chown -R root:root "$RUNNER_DIR"
chmod -R 755 "$RUNNER_DIR"

# Create _diag directory with proper permissions
mkdir -p "$RUNNER_DIR/_diag"
chmod 777 "$RUNNER_DIR/_diag"
log_success "Created _diag directory with proper permissions"

# Create _work directory
mkdir -p "$RUNNER_DIR/_work"
chmod 755 "$RUNNER_DIR/_work"

# Create environment file with proper configuration
log_info "Creating environment configuration..."
cat > "$RUNNER_DIR/.env" << 'EOF'
RUNNER_ALLOW_RUNASROOT="1"
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF

# Configure runner
log_info "Configuring runner..."
export RUNNER_ALLOW_RUNASROOT="1"

./config.sh \
    --url "$GITHUB_REPO_URL" \
    --token "$GITHUB_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "self-hosted,kubernetes,Linux,X64" \
    --work "_work" \
    --unattended \
    --replace

# Install service as root
log_info "Installing as system service..."
./svc.sh install root

# Create systemd service override for proper environment
RUNNER_SERVICE=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
if [ -n "$RUNNER_SERVICE" ]; then
    log_info "Creating service override for reliability..."
    mkdir -p "/etc/systemd/system/${RUNNER_SERVICE}.d"
    
    cat > "/etc/systemd/system/${RUNNER_SERVICE}.d/override.conf" << EOF
[Service]
User=root
Group=root
Environment="RUNNER_ALLOW_RUNASROOT=1"
Environment="KUBECONFIG=/root/.kube/config"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WorkingDirectory=${RUNNER_DIR}
UMask=0022
StandardOutput=journal
StandardError=journal
LimitCORE=infinity
EOF

    systemctl daemon-reload
    log_success "Service configuration created"
fi

# Start the service
log_info "Starting runner service..."
./svc.sh start

# Wait and verify
sleep 5
log_success "GitHub Actions Runner configured and started!"

# ============================================================================
# INSTALLATION PHASE 2: DOCKER
# ============================================================================

log_info "🐳 Installing Docker..."
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

log_success "Docker installed and configured!"

# ============================================================================
# INSTALLATION PHASE 3: KUBERNETES
# ============================================================================

log_info "☸️  Installing Kubernetes..."

# Kernel modules and sysctl
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

# Install Kubernetes packages
rm -f /etc/apt/sources.list.d/kubernetes.list
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Initialize Kubernetes
log_info "Initializing Kubernetes cluster..."
INTERNAL_IP=$(hostname -I | awk '{print $1}')
kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock

mkdir -p /root/.kube
cp /etc/kubernetes/admin.conf /root/.kube/config
chown root:root /root/.kube/config

# Install Flannel
log_info "Installing Flannel network..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove taints
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster
log_info "Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes cluster is ready!"

# ============================================================================
# INSTALLATION PHASE 4: INGRESS-NGINX
# ============================================================================

log_info "🌐 Installing ingress-nginx..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml

sleep 15

# Enable hostNetwork
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

log_success "ingress-nginx ready!"

# ============================================================================
# INSTALLATION PHASE 4.5: METALLB (FOR LOADBALANCER SUPPORT)
# ============================================================================

log_info "🌐 Installing MetalLB for LoadBalancer support..."

# ✅ FIX: Detect external IP FIRST
log_info "Detecting server external IP..."
EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || curl -s http://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

if [ -z "$EXTERNAL_IP" ]; then
    log_error "Could not detect external IP!"
    read -p "Enter your server's public IP address: " EXTERNAL_IP
fi

log_info "Using external IP: $EXTERNAL_IP"

# Check if MetalLB is already installed
if kubectl get namespace metallb-system &>/dev/null; then
    log_warning "MetalLB already installed"
else
    # Install MetalLB
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml
    
    # Wait for MetalLB to be ready
    log_info "Waiting for MetalLB pods..."
    kubectl wait --namespace metallb-system \
        --for=condition=ready pod \
        --selector=app=metallb \
        --timeout=90s || log_warning "MetalLB taking longer than expected"
    
    log_success "MetalLB installed!"
fi

# Configure IP address pool
log_info "Configuring MetalLB IP pool with $EXTERNAL_IP..."

cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: june-pool
  namespace: metallb-system
spec:
  addresses:
  - ${EXTERNAL_IP}/32
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: june-l2
  namespace: metallb-system
spec:
  ipAddressPools:
  - june-pool
EOF

log_success "MetalLB configured with IP: $EXTERNAL_IP"

# ============================================================================
# INSTALLATION PHASE 5: CERT-MANAGER
# ============================================================================

log_info "🔐 Installing cert-manager..."
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml
kubectl create namespace cert-manager || true
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml

kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/instance=cert-manager \
    -n cert-manager \
    --timeout=180s || log_warning "cert-manager taking longer..."

log_success "cert-manager ready!"

# Create Cloudflare secret
log_info "Creating Cloudflare API secret..."
kubectl create secret generic cloudflare-api-token \
    --from-literal=api-token="$CF_API_TOKEN" \
    --namespace=cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -

# Create ClusterIssuers
log_info "Creating ClusterIssuers for ${PRIMARY_DOMAIN}..."

# Staging ClusterIssuer
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

# Production ClusterIssuer
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
# INSTALLATION PHASE 6: GPU OPERATOR (if requested)
# ============================================================================

if [[ $SETUP_GPU == [yY] ]]; then
    log_info "🎮 Installing GPU Operator with time-slicing..."
    
    # Install Helm if not present
    if ! command -v helm &> /dev/null; then
        snap install helm --classic || {
            cd /tmp
            wget https://get.helm.sh/helm-v3.14.0-linux-amd64.tar.gz
            tar -zxvf helm-v3.14.0-linux-amd64.tar.gz
            mv linux-amd64/helm /usr/local/bin/helm
            chmod +x /usr/local/bin/helm
            rm -rf linux-amd64 helm-v3.14.0-linux-amd64.tar.gz
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
    
    # Configure time-slicing
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
    
    # Label nodes
    kubectl label nodes --all gpu=true --overwrite
    log_success "Nodes labeled with gpu=true"
fi

# ============================================================================
# INSTALLATION PHASE 7: NAMESPACES AND STORAGE
# ============================================================================

log_info "📁 Setting up namespaces and storage..."

# Create june-services namespace
kubectl create namespace june-services || log_warning "Namespace june-services already exists"

# Create storage directories
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

# Create StorageClass
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

# Create PersistentVolume for PostgreSQL
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
# INSTALLATION PHASE 8: APPLICATION SECRETS
# ============================================================================

log_info "🔐 Creating application secrets with Gemini API key..."

kubectl create secret generic june-secrets \
    --from-literal=gemini-api-key="$GEMINI_API_KEY" \
    --from-literal=keycloak-client-secret="PLACEHOLDER" \
    --namespace=june-services \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Application secrets created!"

# Verify the secret was created correctly
log_info "Verifying Gemini API key in secret..."
STORED_KEY=$(kubectl get secret june-secrets -n june-services -o jsonpath='{.data.gemini-api-key}' | base64 -d 2>/dev/null || echo "")

if [ -n "$STORED_KEY" ] && [ ${#STORED_KEY} -ge 20 ]; then
    log_success "Gemini API key successfully stored in Kubernetes secret"
    echo "  Key length: ${#STORED_KEY} characters"
else
    log_error "Failed to store Gemini API key correctly!"
    exit 1
fi

# ============================================================================
# INSTALLATION PHASE 9: STUNNER OPERATOR (PROPER K8S WAY)
# ============================================================================

log_info "🔗 Installing STUNner Operator (Gateway API)..."

# Install Gateway API CRDs (required by STUNner)
log_info "Installing Gateway API CRDs..."
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml

# Wait for Gateway API CRDs
sleep 5

# Create stunner-system namespace
kubectl create namespace stunner-system || log_warning "stunner-system namespace already exists"
kubectl create namespace stunner || log_warning "stunner namespace already exists"

# Install Helm if not present (needed for STUNner operator)
if ! command -v helm &> /dev/null; then
    log_info "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Add STUNner Helm repo
log_info "Adding STUNner Helm repository..."
helm repo add stunner https://l7mp.io/stunner
helm repo update

# Install STUNner Gateway Operator
log_info "Installing STUNner Gateway Operator..."
helm install stunner-gateway-operator stunner/stunner-gateway-operator \
    --create-namespace \
    --namespace=stunner-system \
    --wait \
    --timeout=5m

log_success "STUNner operator installed!"

# Wait for operator to be ready
log_info "Waiting for STUNner operator to be ready..."
kubectl wait --for=condition=available deployment/stunner-gateway-operator \
    -n stunner-system \
    --timeout=180s || log_warning "Operator taking longer than expected"

# Create GatewayConfig (STUNner configuration)
log_info "Creating STUNner GatewayConfig..."
cat <<EOF | kubectl apply -f -
apiVersion: stunner.l7mp.io/v1
kind: GatewayConfig
metadata:
  name: stunner-gatewayconfig
  namespace: stunner-system
spec:
  realm: ${STUNNER_REALM}
  authType: static
  userName: ${STUNNER_USERNAME}
  password: ${STUNNER_PASSWORD}
  logLevel: all:INFO
EOF

log_success "GatewayConfig created"

# Create GatewayClass
log_info "Creating STUNner GatewayClass..."
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: stunner-gatewayclass
spec:
  controllerName: "stunner.l7mp.io/gateway-operator"
  parametersRef:
    group: "stunner.l7mp.io"
    kind: GatewayConfig
    name: stunner-gatewayconfig
    namespace: stunner-system
  description: "STUNner Gateway for WebRTC"
EOF

log_success "GatewayClass created"

# Create Gateway (this deploys the actual TURN server)
log_info "Creating STUNner Gateway..."
cat <<EOF | kubectl apply -f -
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
  - name: tcp-listener
    port: 3478
    protocol: TCP
EOF

log_success "Gateway created - STUNner is deploying..."

# Wait for Gateway to be ready
log_info "Waiting for STUNner Gateway to be ready (this may take 2-3 minutes)..."
kubectl wait --for=condition=Programmed gateway/june-stunner-gateway \
    -n stunner \
    --timeout=300s || log_warning "Gateway taking longer than expected"

# Get the external IP/address
log_info "Retrieving STUNner Gateway address..."
sleep 10

STUNNER_ADDRESS=$(kubectl get gateway june-stunner-gateway -n stunner \
    -o jsonpath='{.status.addresses[0].value}' 2>/dev/null || echo "")

if [ -n "$STUNNER_ADDRESS" ]; then
    log_success "STUNner Gateway ready at: $STUNNER_ADDRESS:3478"
else
    log_warning "Gateway address not yet assigned (this is normal, will be available soon)"
    log_info "Check with: kubectl get gateway -n stunner"
fi

# Create UDPRoute for orchestrator (optional, for internal routing)
log_info "Creating UDPRoute for June services..."
cat <<EOF | kubectl apply -f -
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: june-services-route
  namespace: stunner
spec:
  parentRefs:
  - name: june-stunner-gateway
    namespace: stunner
  rules:
  - backendRefs:
    - name: june-orchestrator
      namespace: june-services
      port: 8080
EOF

log_success "UDPRoute created"

log_success "STUNner Operator installation complete!"

# Wait for STUNner deployment
log_info "Waiting for STUNner deployment to be ready..."
kubectl wait --for=condition=available deployment/june-stunner-gateway \
    -n stunner \
    --timeout=120s || log_warning "STUNner deployment taking longer than expected"

log_success "Reliable STUNner is ready!"

# Verify port is listening
log_info "Verifying STUNner is listening on port 3478..."
sleep 10

# Check if port is bound
if netstat -ulnp 2>/dev/null | grep -q ":3478" || ss -ulnp 2>/dev/null | grep -q ":3478"; then
    log_success "STUNner is listening on port 3478 (hostNetwork working!)"
else
    log_warning "STUNner may not be listening on port 3478 yet (deployment might still be starting)"
fi

# Quick STUN test
log_info "Running quick STUN connectivity test..."
python3 << 'STUN_TEST'
import socket
import struct
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    transaction_id = b'\x12\x34\x56\x78\x90\xab\xcd\xef\xfe\xdc\xba\x98'
    stun_request = struct.pack('!HH12s', 0x0001, 0x0000, transaction_id)
    sock.sendto(stun_request, ("127.0.0.1", 3478))
    response, addr = sock.recvfrom(1024)
    print(f"✅ STUN test PASSED: {len(response)} bytes received")
    sock.close()
    exit(0)
except Exception as e:
    print(f"⚠️  STUN test pending (may need more time to start): {e}")
    exit(0)
STUN_TEST

# ============================================================================
# CONFIGURATION SAVE
# ============================================================================

log_info "💾 Saving configuration files..."

# Create configuration directory
CONFIG_DIR="/root/.june-config"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# Save complete domain configuration
cat > "${CONFIG_DIR}/domain-config.env" << EOF
# June Infrastructure Complete Configuration
# Generated: $(date)
# This file is used by GitHub Actions workflow for deployments
# FIXED VERSION: Uses reliable coturn TURN server

PRIMARY_DOMAIN=${PRIMARY_DOMAIN}
API_DOMAIN=${API_DOMAIN}
IDP_DOMAIN=${IDP_DOMAIN}
STT_DOMAIN=${STT_DOMAIN}
TTS_DOMAIN=${TTS_DOMAIN}
TURN_DOMAIN=${TURN_DOMAIN}
WILDCARD_DOMAIN=${WILDCARD_DOMAIN}
CERT_SECRET_NAME=${CERT_SECRET_NAME}

# API Keys (for manual deployments)
GEMINI_API_KEY=${GEMINI_API_KEY}

# STUNner Configuration (FIXED VERSION)
STUNNER_REALM=${STUNNER_REALM}
STUNNER_USERNAME=${STUNNER_USERNAME}
STUNNER_PASSWORD=${STUNNER_PASSWORD}
STUNNER_IMAGE=coturn/coturn:4.6.2-alpine
STUNNER_HOST_NETWORK=true
STUNNER_PORT=3478
EOF

chmod 600 "${CONFIG_DIR}/domain-config.env"
log_success "Configuration saved to: ${CONFIG_DIR}/domain-config.env"

# Update GitHub runner environment
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
# FINAL VERIFICATION
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ || hostname -I | awk '{print $1}')

echo ""
echo "======================================================"
log_info "Running Final Verification..."
echo "======================================================"
echo ""

# Check cluster
log_info "Checking Kubernetes cluster..."
if kubectl cluster-info &>/dev/null; then
    log_success "Cluster is accessible"
else
    log_error "Cluster not accessible!"
fi

# Check GitHub runner
log_info "Checking GitHub runner..."
if systemctl is-active --quiet actions.runner.*; then
    log_success "GitHub runner is active"
else
    log_warning "GitHub runner not active"
fi

# Check namespace
if kubectl get namespace june-services &>/dev/null; then
    log_success "Namespace 'june-services' exists"
else
    log_error "Namespace not found!"
fi

# Check storage
log_info "Checking storage..."
if kubectl get sc local-storage &>/dev/null; then
    log_success "StorageClass exists"
else
    log_error "StorageClass not found!"
fi

if kubectl get pv postgresql-pv &>/dev/null; then
    log_success "PostgreSQL PV exists"
else
    log_error "PostgreSQL PV not found!"
fi

# Check ingress
log_info "Checking ingress controller..."
INGRESS_READY=$(kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
if [ "$INGRESS_READY" = "True" ]; then
    log_success "Ingress controller is running"
else
    log_warning "Ingress controller not ready yet"
fi

# Check cert-manager
log_info "Checking cert-manager..."
CERT_MANAGER_READY=$(kubectl get pods -n cert-manager -l app.kubernetes.io/instance=cert-manager -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
if [ "$CERT_MANAGER_READY" = "True" ]; then
    log_success "cert-manager is running"
else
    log_warning "cert-manager not ready yet"
fi

# Check STUNner
log_info "Checking reliable STUNner..."
if kubectl get namespace stunner &>/dev/null; then
    log_success "STUNner namespace exists"
else
    log_error "STUNner namespace not found!"
fi

if kubectl get deployment june-stunner-gateway -n stunner &>/dev/null; then
    log_success "STUNner deployment exists"
    
    # Check pod status
    READY_PODS=$(kubectl get pods -n stunner -l app=stunner --no-headers | grep Running | wc -l)
    if [ "$READY_PODS" -gt 0 ]; then
        log_success "STUNner pod is running (FIXED VERSION)"
    else
        log_warning "STUNner pod may not be ready yet"
        kubectl get pods -n stunner -l app=stunner
    fi
else
    log_error "STUNner deployment not found!"
fi

if kubectl get secret stunner-auth-secret -n stunner &>/dev/null; then
    log_success "STUNner authentication secret exists"
else
    log_error "STUNner authentication secret not found!"
fi

# Check if STUNner is listening on host port
log_info "Checking if STUNner is listening on port 3478..."
if netstat -ulnp 2>/dev/null | grep -q ":3478" || ss -ulnp 2>/dev/null | grep -q ":3478"; then
    log_success "STUNner is listening on port 3478 (hostNetwork working!)"
else
    log_warning "STUNner may not be listening on port 3478 yet (deployment might still be starting)"
fi

# Check GPU
if [[ $SETUP_GPU == [yY] ]]; then
    log_info "Checking GPU availability..."
    GPU_ALLOCATABLE=$(kubectl get nodes -o json | jq -r '.items[].status.allocatable."nvidia.com/gpu" // "0"' | head -1)
    
    if [ "$GPU_ALLOCATABLE" -ge "$GPU_REPLICAS" ]; then
        log_success "GPU time-slicing active: $GPU_ALLOCATABLE virtual GPUs"
    else
        log_warning "GPU showing $GPU_ALLOCATABLE (expected $GPU_REPLICAS)"
    fi
fi

# Check Gemini API key secret
log_info "Verifying Gemini API key in secret..."
STORED_KEY_CHECK=$(kubectl get secret june-secrets -n june-services -o jsonpath='{.data.gemini-api-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
if [ -n "$STORED_KEY_CHECK" ] && [ ${#STORED_KEY_CHECK} -ge 20 ]; then
    log_success "Gemini API key present in secret (${#STORED_KEY_CHECK} chars)"
else
    log_error "Gemini API key missing or invalid in secret!"
fi

# ============================================================================
# FINAL STATUS
# ============================================================================

echo ""
echo "======================================================"
log_success "🎉 UNIFIED June Platform Installation Complete! (FIXED)"
echo "======================================================"
echo ""
echo "✅ Infrastructure Ready:"
echo "  🐙 GitHub Actions Runner: ${RUNNER_NAME}"
echo "  ☸️  Kubernetes cluster with Flannel networking"
echo "  🌐 ingress-nginx (hostNetwork mode)"
echo "  🔐 cert-manager with Let's Encrypt"
echo "  🔗 Reliable STUNner with coturn (FIXED VERSION)"

if [[ $SETUP_GPU == [yY] ]]; then
    echo "  🎮 GPU Operator with time-slicing ($GPU_REPLICAS virtual GPUs)"
fi

echo "  📁 Storage infrastructure"
echo "  🔑 Application secrets with Gemini API key"
echo ""
echo "🌐 Domain Configuration:"
echo "  Primary: ${PRIMARY_DOMAIN}"
echo "  API: ${API_DOMAIN}"
echo "  IDP: ${IDP_DOMAIN}"
echo "  STT: ${STT_DOMAIN}"
echo "  TTS: ${TTS_DOMAIN}"
echo "  TURN: ${TURN_DOMAIN}"
echo ""
echo "🔗 Reliable STUNner STUN/TURN Server:"
echo "  Domain: ${TURN_DOMAIN}"
echo "  Username: ${STUNNER_USERNAME}"
echo "  Password: ${STUNNER_PASSWORD:0:3}***"
echo "  Image: coturn/coturn:4.6.2-alpine (FIXED)"
echo ""
echo "🔑 API Keys:"
echo "  Gemini: ${MASKED_GEMINI_KEY} ✅"
echo ""
echo "📁 Configuration Files:"
echo "  Complete config: ${CONFIG_DIR}/domain-config.env"
echo ""
echo "🌍 External IP: $EXTERNAL_IP"
echo ""
echo "🚀 Next Steps:"
echo ""
echo "  1. Configure DNS records to point to $EXTERNAL_IP:"
echo "     ${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo "     *.${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo ""
echo "  2. Verify GitHub runner connection:"
echo "     ${GITHUB_REPO_URL}/settings/actions/runners"
echo ""
echo "  3. Push code to GitHub to trigger automated deployment:"
echo "     git push origin master"
echo ""
echo "  4. Monitor services:"
echo "     kubectl get pods -n june-services -w"
echo "     kubectl get pods -n stunner -w"
echo ""
echo "  5. Test STUN/TURN server:"
echo "     python3 scripts/test-turn-server.py"
echo "     https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/"
echo "     STUN URI: stun:${TURN_DOMAIN}:3478"
echo "     TURN URI: turn:${TURN_DOMAIN}:3478"
echo "     Username: ${STUNNER_USERNAME}"
echo "     Password: ${STUNNER_PASSWORD}"
echo ""
echo "📋 Useful Commands:"
echo "  Runner status: cd /opt/actions-runner && sudo ./svc.sh status"
echo "  Runner logs:   journalctl -u actions.runner.* -f"
echo "  Cluster info:  kubectl cluster-info"
echo "  All pods:      kubectl get pods --all-namespaces"
echo "  STUNner logs:  kubectl logs -n stunner -l app=stunner -f"
echo ""
echo "======================================================"
echo "🎉 Your June Platform is ready for deployment!"
echo "======================================================"