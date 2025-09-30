#!/bin/bash
# Enhanced Kubernetes Setup Script for GPU-enabled June AI services
# Complete bootstrap solution with NVIDIA GPU support
# Version 3.0 - GPU-Optimized Edition

set -e

echo "======================================================"
echo "🚀 Enhanced Kubernetes Setup Script v3.0 (GPU Edition)"
echo "======================================================"

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
        return 0
    else
        echo "❌ No NVIDIA GPU or drivers detected"
        return 1
    fi
}

# Function to install NVIDIA drivers (if not present)
install_nvidia_drivers() {
    echo "🔧 Installing NVIDIA drivers..."
    
    # Update system first
    apt-get update
    
    # Install recommended driver
    ubuntu-drivers autoinstall
    
    # Alternative method if autoinstall doesn't work
    if ! command -v nvidia-smi &> /dev/null; then
        echo "⚠️ Autoinstall failed, trying manual installation..."
        apt-get install -y nvidia-driver-535 nvidia-dkms-535
    fi
    
    echo "🔄 System reboot may be required after driver installation"
    echo "   Run 'sudo reboot' and re-run this script if nvidia-smi doesn't work"
}

# Function to install NVIDIA Container Toolkit
install_nvidia_container_toolkit() {
    echo "🐳 Installing NVIDIA Container Toolkit..."
    
    # Add NVIDIA Container Toolkit repository
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /" | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    
    # Update package list and install
    apt-get update
    apt-get install -y nvidia-container-toolkit
    
    echo "✅ NVIDIA Container Toolkit installed"
}

# Function to configure containerd for GPU support
configure_containerd_gpu() {
    echo "⚙️ Configuring containerd for GPU support..."
    
    # Generate default containerd config if it doesn't exist
    if [ ! -f /etc/containerd/config.toml ]; then
        containerd config default | tee /etc/containerd/config.toml > /dev/null
    fi
    
    # Configure containerd to use systemd cgroups
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    
    # Configure NVIDIA Container Toolkit for containerd
    nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd/config.toml
    
    # Restart containerd to apply changes
    systemctl restart containerd
    systemctl enable containerd
    
    echo "✅ containerd configured for GPU support"
}

# Function to setup GPU support with latest device plugin
setup_gpu_support() {
    echo "🎮 Setting up GPU support in Kubernetes..."
    
    # Check if NVIDIA GPU is present
    if ! command -v nvidia-smi &> /dev/null; then
        echo "❌ NVIDIA GPU drivers not detected. Installing drivers first..."
        install_nvidia_drivers
        echo "⚠️ Please reboot and re-run this script to continue with GPU setup"
        return 1
    fi
    
    echo "📱 NVIDIA GPU detected, configuring device plugin..."
    
    # Install NVIDIA Container Toolkit if not present
    if ! command -v nvidia-ctk &> /dev/null; then
        install_nvidia_container_toolkit
        configure_containerd_gpu
    fi
    
    # Wait for cluster to be ready before installing device plugin
    echo "⏳ Waiting for cluster to be ready..."
    kubectl wait --for=condition=Ready nodes --all --timeout=300s
    
    # Install latest NVIDIA Device Plugin (v0.17.4 as of Sept 2025)
    echo "🔌 Installing NVIDIA Device Plugin v0.17.4..."
    kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.4/deployments/static/nvidia-device-plugin.yml
    
    # Wait for device plugin to be ready
    echo "⏳ Waiting for NVIDIA Device Plugin to be ready..."
    kubectl wait --namespace kube-system \
        --for=condition=ready pod \
        --selector=name=nvidia-device-plugin-ds \
        --timeout=120s || {
        echo "⚠️ Device plugin taking longer than expected, continuing..."
    }
    
    # Verify GPU resources are available
    echo "🔍 Verifying GPU resources..."
    sleep 10
    GPU_COUNT=$(kubectl get nodes -o jsonpath='{.items[*].status.capacity.nvidia\.com/gpu}' | tr ' ' '+' | bc 2>/dev/null || echo "0")
    
    if [ "$GPU_COUNT" -gt 0 ]; then
        echo "✅ GPU support configured successfully! $GPU_COUNT GPU(s) available"
        kubectl get nodes -o wide
        echo ""
        kubectl describe nodes | grep -A 5 "Capacity:" | grep "nvidia.com/gpu"
    else
        echo "⚠️ GPU resources not yet visible. This may take a few minutes..."
        echo "   You can check later with: kubectl describe nodes | grep nvidia.com/gpu"
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
    
    echo "✅ GPU test pod created. Check with: kubectl logs gpu-test"
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
    
    echo "🔐 Please authenticate with GitHub:"
    gh auth login --web
}

# Function to setup secrets and environment variables
setup_secrets() {
    echo "🔐 Setting up secrets and environment variables..."
    
    prompt_input "Enter your Docker Hub username" DOCKERHUB_USERNAME
    prompt_input "Enter your Docker Hub token" DOCKERHUB_TOKEN
    prompt_input "Enter your Docker Hub email" DOCKERHUB_EMAIL
    prompt_input "Enter your Gemini API key" GEMINI_API_KEY
    prompt_input "Enter your Chatterbox API key (optional)" CHATTERBOX_API_KEY ""
    
    # Create GitHub repository secrets (requires gh CLI)
    if command -v gh &> /dev/null && gh auth status &> /dev/null; then
        echo "📝 Setting up GitHub repository secrets..."
        echo "$DOCKERHUB_USERNAME" | gh secret set DOCKERHUB_USERNAME
        echo "$DOCKERHUB_TOKEN" | gh secret set DOCKERHUB_TOKEN
        echo "$DOCKERHUB_EMAIL" | gh secret set DOCKERHUB_EMAIL
        echo "✅ GitHub secrets configured"
    else
        echo "⚠️  GitHub CLI not authenticated. Please manually set these repository secrets:"
        echo "   - DOCKERHUB_USERNAME: $DOCKERHUB_USERNAME"
        echo "   - DOCKERHUB_TOKEN: [your token]"
        echo "   - DOCKERHUB_EMAIL: $DOCKERHUB_EMAIL"
    fi
    
    # Create Kubernetes secrets
    kubectl create namespace june || true
    kubectl create secret generic june-secrets \
        --from-literal=gemini-api-key="$GEMINI_API_KEY" \
        --from-literal=chatterbox-api-key="$CHATTERBOX_API_KEY" \
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

# Function to standardize namespaces
standardize_namespaces() {
    echo "📝 Standardizing namespaces..."
    
    # Only update if k8s directory exists
    if [ -d "k8s/" ]; then
        # Update manifest files to use consistent namespace
        find k8s/ -name "*.yaml" -exec sed -i 's/namespace: june-services/namespace: june/g' {} \; 2>/dev/null || true
        echo "✅ Namespaces standardized to 'june'"
    else
        echo "ℹ️  No k8s directory found, skipping namespace standardization"
    fi
}

# Function to validate deployment
validate_deployment() {
    echo "🔍 Validating deployment readiness..."
    
    # Check if Docker Hub credentials work
    if echo "$DOCKERHUB_TOKEN" | docker login --username "$DOCKERHUB_USERNAME" --password-stdin docker.io 2>/dev/null; then
        echo "✅ Docker Hub authentication successful"
        
        # Check if all required images exist in Docker Hub
        IMAGES=("june-stt" "june-tts" "june-orchestrator" "june-idp" "june-web" "june-dark")
        
        for image in "${IMAGES[@]}"; do
            if docker manifest inspect "$DOCKERHUB_USERNAME/$image:latest" >/dev/null 2>&1; then
                echo "✅ $image image found"
            else
                echo "⚠️  $image image not found in Docker Hub - you'll need to build and push it"
            fi
        done
    else
        echo "⚠️  Docker Hub authentication failed - please check credentials"
    fi
    
    # Validate Kubernetes manifests if they exist
    if [ -d "k8s/" ]; then
        echo "🔍 Validating Kubernetes manifests..."
        for file in k8s/*.yaml; do
            if [ -f "$file" ]; then
                if kubectl apply --dry-run=client -f "$file" >/dev/null 2>&1; then
                    echo "✅ $(basename $file) is valid"
                else
                    echo "❌ $(basename $file) has validation errors"
                fi
            fi
        done
    fi
    
    # GPU validation
    if command -v nvidia-smi &> /dev/null; then
        echo "🎮 GPU validation:"
        kubectl describe nodes | grep -A 3 "Capacity:" | grep "nvidia.com/gpu" || \
            echo "⚠️  GPU resources not yet visible in Kubernetes"
    fi
}

# Function for cleanup on failure
cleanup_on_failure() {
    echo "🧹 Cleaning up failed installation..."
    
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
    prompt_input "Setup GPU support? (y/n)" SETUP_GPU "y"
else
    echo "❌ No GPU detected. GPU support will be skipped."
    SETUP_GPU="n"
fi

prompt_input "Create GPU test workload? (y/n)" CREATE_GPU_TEST "y"

echo ""
echo "🔍 Configuration Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  GPU Support: $SETUP_GPU"
echo "  GPU Test: $CREATE_GPU_TEST"
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

# GPU setup before Kubernetes if requested
if [[ $SETUP_GPU == [yY] ]]; then
    echo "🎮 Setting up GPU support (pre-Kubernetes)..."
    
    # Install NVIDIA drivers if not present
    if ! command -v nvidia-smi &> /dev/null; then
        install_nvidia_drivers
        echo "⚠️ GPU drivers installed. Please reboot and re-run this script."
        exit 0
    fi
    
    # Install and configure NVIDIA Container Toolkit
    install_nvidia_container_toolkit
    configure_containerd_gpu
else
    # Configure containerd without GPU support
    echo "🔧 Configuring containerd..."
    systemctl stop containerd
    containerd config default | tee /etc/containerd/config.toml > /dev/null
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    systemctl start containerd
    systemctl enable containerd
fi

# Enable required kernel modules
echo "🔧 Setting up kernel modules..."
modprobe br_netfilter
echo 'br_netfilter' >> /etc/modules-load.d/k8s.conf
echo 'net.bridge.bridge-nf-call-ip6tables = 1' >> /etc/sysctl.d/k8s.conf
echo 'net.bridge.bridge-nf-call-iptables = 1' >> /etc/sysctl.d/k8s.conf
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.d/k8s.conf
sysctl --system

# Install Kubernetes using NEW repository
echo "☸️  Installing Kubernetes..."
# Remove old repository if it exists
rm -f /etc/apt/sources.list.d/kubernetes.list

# Create keyrings directory
mkdir -p /etc/apt/keyrings

# Add the new Kubernetes repository
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list

# Update and install
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

# Remove control plane taints to allow scheduling on master
echo "🔧 Configuring single-node cluster..."
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

# Setup GPU support if requested (post-Kubernetes)
if [[ $SETUP_GPU == [yY] ]]; then
    setup_gpu_support
fi

# Prepare for GitHub Actions runner (INTEGRATED FIX)
prepare_github_runner

# Install enhanced components
install_github_cli
setup_secrets
install_ingress_controller
setup_storage
standardize_namespaces

# Create GPU test workload if requested
if [[ $SETUP_GPU == [yY] && $CREATE_GPU_TEST == [yY] ]]; then
    create_gpu_test_pod
fi

# Validate deployment
validate_deployment

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
    echo "  • 🎮 GPU support configured with NVIDIA Device Plugin v0.17.4"
    echo "  • 🐳 NVIDIA Container Toolkit integrated with containerd"
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
    echo "  • Check GPU availability: kubectl describe nodes | grep nvidia.com/gpu"
    echo "  • View test pod logs: kubectl logs gpu-test"
    echo "  • Run GPU workload:"
    echo "    kubectl run gpu-example --image=nvidia/cuda:12.2.2-base-ubuntu22.04 \\"
    echo "    --rm -it --restart=Never --limits nvidia.com/gpu=1 -- nvidia-smi"
    echo ""
fi
echo "🔍 Useful Commands:"
echo "  • View cluster: kubectl get all -A"
echo "  • Check ingress: kubectl get ingress -A"
echo "  • Monitor deployments: kubectl get pods -n june -w"
echo "  • Fix runner after install: /root/fix-github-runner.sh"
echo ""
echo "🌐 Your external IP: $EXTERNAL_IP"
echo "📱 Access your services via ingress once deployed"
echo ""
echo "💡 GitHub Actions Workflow:"
echo "  Step 1: sudo ./install-k8s-ubuntu-gpu.sh  ✅ (Just completed)"
echo "  Step 2: sudo ./stage1-runner-only.sh"
echo "  Step 3: /root/fix-github-runner.sh  (auto-fixes kubectl access)"
echo ""
echo "======================================================"