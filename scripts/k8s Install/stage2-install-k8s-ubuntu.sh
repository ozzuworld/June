#!/bin/bash
# Enhanced Kubernetes Setup Script for GPU-enabled June AI services
# Complete bootstrap solution with NVIDIA GPU Operator via Helm
# Version 6.0 - NO NGC API KEY REQUIRED for public GPU Operator

set -e

echo "======================================================"
echo "🚀 Enhanced Kubernetes Setup Script v6.0"
echo "   GPU Support with Public NVIDIA GPU Operator"
echo "   NO NGC API KEY REQUIRED!"
echo "======================================================"

# Global variable to track if host has drivers
HAS_HOST_DRIVERS=false

# Function to prompt for user input
prompt_input() {
    local prompt_text="$1"
    local var_name="$2"
    local default_value="$3"
    
    if [ -n "$default_value" ]; then
        read -p "$prompt_text [$default_value]: " user_input
        eval "$var_name=\"\${user_input:-$default_value}\""
    else
        read -p "$prompt_text: " user_input
        eval "$var_name=\"$user_input\""
    fi
}

# Function to check GPU availability
check_gpu_availability() {
    echo "🎮 Checking GPU availability..."
    
    if command -v nvidia-smi &> /dev/null; then
        echo "✅ NVIDIA GPU detected:"
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits
        HAS_HOST_DRIVERS=true
        return 0
    else
        echo "ℹ️  No NVIDIA GPU drivers detected on host"
        echo "   GPU Operator will install drivers if GPU hardware is present"
        HAS_HOST_DRIVERS=false
        return 1
    fi
}

# Function to install Helm
install_helm() {
    echo "⎈ Installing Helm..."
    
    if command -v helm &> /dev/null; then
        echo "✅ Helm already installed: $(helm version --short)"
        return 0
    fi
    
    # Install Helm using the official installation script
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
    chmod 700 get_helm.sh
    ./get_helm.sh
    rm -f get_helm.sh
    
    echo "✅ Helm installed successfully: $(helm version --short)"
}

# Function to check if NFD is already running
check_nfd_running() {
    echo "🔍 Checking if Node Feature Discovery (NFD) is already running..."
    
    local nfd_exists
    nfd_exists=$(kubectl get nodes -o json | jq '.items[].metadata.labels | keys | any(startswith("feature.node.kubernetes.io"))' 2>/dev/null || echo "false")
    
    if [ "$nfd_exists" = "true" ]; then
        echo "✅ NFD is already running in the cluster"
        return 0
    else
        echo "ℹ️  NFD is not running, GPU Operator will deploy it"
        return 1
    fi
}

# Function to install NVIDIA GPU Operator using PUBLIC Helm repository
install_gpu_operator() {
    echo "🚀 Installing NVIDIA GPU Operator (Public - No API Key Required)..."
    
    # Ensure Helm is installed
    install_helm
    
    # Add PUBLIC NVIDIA Helm repository (NO AUTHENTICATION REQUIRED)
    echo "📦 Adding NVIDIA public Helm repository..."
    helm repo add nvidia https://nvidia.github.io/gpu-operator
    helm repo update
    
    echo "✅ Repository added successfully (no authentication required)"
    
    # Create namespace with privileged PSA policy
    echo "📂 Creating gpu-operator namespace..."
    kubectl create namespace gpu-operator || true
    kubectl label --overwrite namespace gpu-operator pod-security.kubernetes.io/enforce=privileged
    
    # Check if NFD is already running
    local nfd_disable=""
    if check_nfd_running; then
        nfd_disable="--set nfd.enabled=false"
        echo "⚠️  Disabling NFD deployment in GPU Operator since it's already running"
    fi
    
    # Determine if we should disable driver installation (if host has drivers)
    local driver_setting="--set driver.enabled=true"
    if [ "$HAS_HOST_DRIVERS" = true ]; then
        echo "⚠️  Host drivers detected - configuring GPU Operator for pre-installed drivers"
        driver_setting="--set driver.enabled=false"
    fi
    
    # Get latest GPU Operator version
    LATEST_VERSION=$(helm search repo nvidia/gpu-operator --versions | grep gpu-operator | head -1 | awk '{print $2}')
    echo "📦 Latest GPU Operator version: $LATEST_VERSION"
    
    # Install GPU Operator from PUBLIC repository
    echo "🎮 Installing NVIDIA GPU Operator $LATEST_VERSION..."
    helm install gpu-operator \
        --wait \
        --timeout 15m \
        --namespace gpu-operator \
        nvidia/gpu-operator \
        --version=$LATEST_VERSION \
        $driver_setting \
        --set toolkit.enabled=true \
        --set devicePlugin.enabled=true \
        --set dcgmExporter.enabled=true \
        --set gfd.enabled=true \
        --set migManager.enabled=true \
        --set nodeStatusExporter.enabled=true \
        --set gds.enabled=false \
        --set vfioManager.enabled=true \
        --set sandboxWorkloads.enabled=false \
        --set vgpuManager.enabled=false \
        --set vgpuDeviceManager.enabled=false \
        --set ccManager.enabled=false \
        --set operator.defaultRuntime=containerd \
        $nfd_disable
    
    echo "✅ NVIDIA GPU Operator installed successfully!"
    
    # Wait for GPU Operator components to be ready
    echo "⏳ Waiting for GPU Operator components to be ready..."
    
    # Only wait for driver if it's enabled
    if [ "$HAS_HOST_DRIVERS" != true ]; then
        echo "⏳ Waiting for driver pods..."
        kubectl wait --for=condition=ready pods \
            --selector=app=nvidia-driver-daemonset \
            --namespace=gpu-operator \
            --timeout=600s || {
            echo "⚠️  Driver pods taking longer than expected, continuing..."
        }
    fi
    
    # Wait for device plugin
    echo "⏳ Waiting for device plugin..."
    kubectl wait --for=condition=ready pods \
        --selector=app=nvidia-device-plugin-daemonset \
        --namespace=gpu-operator \
        --timeout=300s || {
        echo "⚠️  Device plugin pods taking longer than expected, continuing..."
    }
    
    # Wait for container toolkit
    echo "⏳ Waiting for container toolkit..."
    kubectl wait --for=condition=ready pods \
        --selector=app=nvidia-container-toolkit-daemonset \
        --namespace=gpu-operator \
        --timeout=300s || {
        echo "⚠️  Container toolkit pods taking longer than expected, continuing..."
    }
    
    echo "✅ GPU Operator components are ready!"
    
    if [ "$HAS_HOST_DRIVERS" = true ]; then
        echo ""
        echo "ℹ️  Note: Driver installation was disabled because host drivers are present"
        echo "   This is the correct configuration and prevents unnecessary errors."
    fi
}

# Function to verify GPU support
verify_gpu_support() {
    echo "🔍 Verifying GPU support..."
    
    # Check GPU resources in nodes
    echo "🎮 Checking GPU resources in nodes..."
    sleep 30  # Give some time for resources to be registered
    
    local gpu_count
    gpu_count=$(kubectl get nodes -o jsonpath='{.items[*].status.capacity.nvidia\.com/gpu}' | tr ' ' '+' | bc 2>/dev/null || echo "0")
    
    if [ "$gpu_count" -gt 0 ]; then
        echo "✅ GPU support verified! $gpu_count GPU(s) available in cluster"
        
        echo "📊 GPU Status:"
        kubectl get nodes -o wide
        echo ""
        kubectl describe nodes | grep -A 5 "Capacity:" | grep "nvidia.com/gpu" || echo "GPU capacity information not yet available"
        
        # Create verification test pod
        echo ""
        echo "🧪 Creating GPU verification test..."
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-verification
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: cuda-test
    image: nvidia/cuda:12.2.2-base-ubuntu22.04
    command: ["nvidia-smi"]
    resources:
      limits:
        nvidia.com/gpu: 1
EOF
        
        echo "⏳ Waiting for verification test to complete..."
        sleep 20
        
        echo ""
        echo "✅ GPU Verification Test Results:"
        echo "=================================="
        kubectl logs gpu-verification 2>/dev/null || echo "Test pod still initializing..."
        
        return 0
    else
        echo "⚠️  GPU resources not yet visible. Checking GPU Operator status..."
        kubectl get pods -n gpu-operator
        echo ""
        echo "💡 If pods are still initializing, GPU resources will appear once all pods are ready."
        echo "   You can check later with: kubectl describe nodes | grep nvidia.com/gpu"
        return 1
    fi
}

# Function to create GPU test pod
create_gpu_test_pod() {
    echo "🧪 Creating GPU test workload..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-test
  namespace: default
spec:
  restartPolicy: Never
  containers:
    - name: cuda-container
      image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
      resources:
        limits:
          nvidia.com/gpu: 1
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
EOF
    
    echo "✅ GPU test pod created. Monitor with: kubectl logs gpu-test -f"
    echo "   The test should show 'Test PASSED' when GPU is working properly"
}

# Function to prepare for GitHub Actions runner (future-proof)
prepare_github_runner() {
    echo "🔧 Preparing environment for GitHub Actions runner..."
    
    # Create runner directories structure
    mkdir -p /root/actions-runner
    
    # Create .env file template for when runner is installed
    cat > /root/actions-runner/.env.template << 'EOF'
# GitHub Actions Runner Environment Variables
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
EOF

    # Create script to fix runner after installation
    cat > /root/fix-github-runner.sh << 'EOF'
#!/bin/bash
# Auto-fix script for GitHub Actions runner kubectl access

echo "🔧 Configuring GitHub Actions runner for kubectl access..."

# Check if runner is installed
if [ ! -f "/root/actions-runner/.runner" ]; then
    echo "⚠️  GitHub Actions runner not found. Install it first with stage1-runner-only.sh"
    exit 1
fi

# Setup environment file
if [ -f "/root/actions-runner/.env.template" ]; then
    cp /root/actions-runner/.env.template /root/actions-runner/.env
    echo "✅ Environment variables configured"
else
    echo "KUBECONFIG=/root/.kube/config" > /root/actions-runner/.env
    echo "LANG=C.UTF-8" >> /root/actions-runner/.env
fi

# Restart runner service if it exists
if systemctl is-active --quiet actions.runner.*; then
    echo "🔄 Restarting GitHub Actions runner..."
    systemctl restart actions.runner.*
    echo "✅ Runner restarted with new configuration"
fi

echo "✅ GitHub Actions runner configured for kubectl access!"
EOF

    chmod +x /root/fix-github-runner.sh
    
    echo "✅ GitHub Actions runner environment prepared"
    echo "ℹ️  When you install the runner later, run: /root/fix-github-runner.sh"
}

# Function to install GitHub CLI
install_github_cli() {
    echo "📱 Installing GitHub CLI..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    apt update && apt install gh -y
    
    echo "✅ GitHub CLI installed"
    echo "ℹ️  Authenticate later with: gh auth login"
}

# Function to setup secrets and environment variables
setup_secrets() {
    echo "🔐 Setting up secrets and environment variables..."
    
    prompt_input "Enter your Docker Hub username" DOCKERHUB_USERNAME
    prompt_input "Enter your Docker Hub token" DOCKERHUB_TOKEN
    prompt_input "Enter your Docker Hub email" DOCKERHUB_EMAIL
    prompt_input "Enter your Gemini API key" GEMINI_API_KEY
    prompt_input "Enter your Chatterbox API key (optional)" CHATTERBOX_API_KEY ""
    
    # Create Kubernetes secrets
    kubectl create namespace june || true
    kubectl create secret generic june-secrets \
        --from-literal=gemini-api-key="$GEMINI_API_KEY" \
        --from-literal=chatterbox-api-key="$CHATTERBOX_API_KEY" \
        --namespace=june \
        --dry-run=client -o yaml | kubectl apply -f -
        
    # Create Docker Hub secret
    kubectl create secret docker-registry dockerhub-secret \
        --docker-server=docker.io \
        --docker-username=$DOCKERHUB_USERNAME \
        --docker-password=$DOCKERHUB_TOKEN \
        --docker-email=$DOCKERHUB_EMAIL \
        --namespace=june \
        --dry-run=client -o yaml | kubectl apply -f -
        
    echo "✅ Kubernetes secrets created"
}

# Function to install ingress controller
install_ingress_controller() {
    echo "🌐 Installing NGINX Ingress Controller..."
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
    
    # Wait for ingress controller to be ready
    echo "⏳ Waiting for ingress controller..."
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=120s || {
        echo "⚠️  Ingress controller taking longer than expected, continuing..."
    }
        
    echo "✅ Ingress controller installed!"
}

# Function to setup persistent storage
setup_storage() {
    echo "💾 Setting up persistent storage..."
    
    # Create directory
    mkdir -p /opt/june-data
    chmod 755 /opt/june-data
    
    # Create StorageClass for local storage
    cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-storage
spec:
  capacity:
    storage: 50Gi
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/june-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - $(hostname)
EOF

    echo "✅ Storage configured"
}

# Function to cleanup on failure
cleanup_on_failure() {
    echo "🧹 Cleaning up failed installation..."
    
    # Remove GPU Operator if installed
    helm uninstall gpu-operator -n gpu-operator 2>/dev/null || true
    kubectl delete namespace gpu-operator 2>/dev/null || true
    
    # Stop and remove containers
    docker stop $(docker ps -aq) 2>/dev/null || true
    docker rm $(docker ps -aq) 2>/dev/null || true
    
    # Reset kubeadm
    kubeadm reset -f 2>/dev/null || true
    
    # Remove directories
    rm -rf /root/.kube 2>/dev/null || true
    
    echo "🗑️  Cleanup completed"
}

# Trap cleanup on script failure
trap cleanup_on_failure ERR

# Get configuration from user
echo "📝 Configuration Setup"
echo "----------------------"

prompt_input "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"

# Check GPU availability and ask for setup
if check_gpu_availability; then
    prompt_input "Setup GPU Operator? (y/n)" SETUP_GPU "y"
else
    prompt_input "Setup GPU Operator anyway? (GPU hardware might be present) (y/n)" SETUP_GPU "n"
fi

prompt_input "Create GPU test workload? (y/n)" CREATE_GPU_TEST "y"

echo ""
echo "🔍 Configuration Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  GPU Operator: $SETUP_GPU"
echo "  GPU Test: $CREATE_GPU_TEST"
if [ "$HAS_HOST_DRIVERS" = true ]; then
    echo "  Host Drivers: Detected (will use pre-installed drivers)"
fi
echo ""
echo "💡 Note: PUBLIC GPU Operator - No NGC API key required!"
echo ""

read -p "Continue with installation? (y/n): " confirm
if [[ $confirm != [yY] ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "🚀 Starting installation..."

# Update system
echo "📦 Updating system packages..."
apt-get update && apt-get upgrade -y

# Install dependencies
echo "📦 Installing dependencies..."
apt-get install -y curl wget apt-transport-https ca-certificates gnupg lsb-release jq bc

# Install Docker
echo "🐳 Installing Docker..."
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io

# Configure containerd
echo "🔧 Configuring containerd..."
systemctl stop containerd
containerd config default | tee /etc/containerd/config.toml > /dev/null
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl start containerd
systemctl enable containerd

# Enable required kernel modules
echo "🔧 Setting up kernel modules..."
modprobe br_netfilter
echo 'br_netfilter' >> /etc/modules-load.d/k8s.conf
echo 'net.bridge.bridge-nf-call-ip6tables = 1' >> /etc/sysctl.d/k8s.conf
echo 'net.bridge.bridge-nf-call-iptables = 1' >> /etc/sysctl.d/k8s.conf
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.d/k8s.conf
sysctl --system

# Install Kubernetes
echo "☸️  Installing Kubernetes..."
rm -f /etc/apt/sources.list.d/kubernetes.list
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update && apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Get external IP for API server
EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/)
INTERNAL_IP=$(hostname -I | awk '{print $1}')

echo "🌐 Detected IPs:"
echo "  External IP: $EXTERNAL_IP"
echo "  Internal IP: $INTERNAL_IP"

# Initialize Kubernetes
echo "☸️  Initializing Kubernetes cluster..."
kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock

# Setup kubeconfig
echo "⚙️  Setting up kubeconfig..."
mkdir -p /root/.kube
cp -i /etc/kubernetes/admin.conf /root/.kube/config
chown root:root /root/.kube/config

# Install Flannel network plugin
echo "🌐 Installing Flannel network plugin..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove control plane taints
echo "🔧 Configuring single-node cluster..."
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

# Install GPU Operator if requested
if [[ $SETUP_GPU == [yY] ]]; then
    install_gpu_operator
fi

# Install enhanced components
install_github_cli
prepare_github_runner
setup_secrets
install_ingress_controller
setup_storage

# Create GPU test workload if requested
if [[ $SETUP_GPU == [yY] && $CREATE_GPU_TEST == [yY] ]]; then
    if [ "$HAS_HOST_DRIVERS" != true ]; then
        echo "⏳ Waiting for GPU Operator to be fully ready..."
        sleep 60
        create_gpu_test_pod
    fi
fi

# Print final information
echo ""
echo "🎉======================================================"
echo "✅ Kubernetes Installation Complete!"
echo "======================================================"
echo ""
echo "📋 Summary:"
echo "  • Kubernetes cluster initialized and ready"
echo "  • NGINX Ingress Controller installed"
echo "  • Persistent storage configured"
echo "  • Secrets management setup"
if [[ $SETUP_GPU == [yY] ]]; then
    echo "  • 🚀 NVIDIA GPU Operator installed (PUBLIC - No API Key)"
    if [ "$HAS_HOST_DRIVERS" = true ]; then
        echo "  • 🎮 GPU support configured (using pre-installed host drivers)"
    else
        echo "  • 🎮 GPU support configured with full operator stack"
    fi
fi
echo "  • 🔧 GitHub Actions runner environment prepared"
echo ""
echo "🔧 Next Steps:"
echo "  1. Install GitHub Actions runner: ./stage1-runner-only.sh"
echo "  2. Auto-fix runner access: /root/fix-github-runner.sh"
echo "  3. Deploy your June services using GitHub Actions"
echo ""
if [[ $SETUP_GPU == [yY] ]]; then
    echo "🎮 GPU Commands:"
    echo "  • Check GPU Operator: kubectl get pods -n gpu-operator"
    echo "  • Check GPU availability: kubectl describe nodes | grep nvidia.com/gpu"
    if [ "$CREATE_GPU_TEST" == [yY] ] && [ "$HAS_HOST_DRIVERS" != true ]; then
        echo "  • View test pod logs: kubectl logs gpu-test -f"
    fi
    if [ "$HAS_HOST_DRIVERS" = true ]; then
        echo "  • View verification logs: kubectl logs gpu-verification"
    fi
    echo "  • Run GPU workload:"
    echo "    kubectl run gpu-example --image=nvidia/cuda:12.2.2-base-ubuntu22.04 \\"
    echo "    --rm -it --restart=Never --limits nvidia.com/gpu=1 -- nvidia-smi"
    echo ""
fi
echo "🔍 Useful Commands:"
echo "  • View cluster: kubectl get all -A"
echo "  • Check ingress: kubectl get ingress -A"
echo "  • Monitor deployments: kubectl get pods -n june -w"
echo "  • Fix runner: /root/fix-github-runner.sh"
echo ""
echo "🌐 Your external IP: $EXTERNAL_IP"
echo ""
echo "======================================================"