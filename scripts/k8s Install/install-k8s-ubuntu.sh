#!/bin/bash
# Enhanced Kubernetes + GitHub Actions Runner Setup Script for Vast.ai
# Version: 2.1 - Token Expiration Fix (Runner Setup First)

set -e

echo "======================================================"
echo "🚀 Enhanced K8s + GitHub Actions Runner Setup Script"
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

# Function to check if we're in a git repository
check_repository() {
    if [ -d ".git" ] && [ -f "enhanced-k8s-bootstrap.sh" ]; then
        echo "✅ Running from ozzuworld/june repository"
        REPO_MODE=true
        REPO_PATH=$(pwd)
    else
        echo "⚠️  Not running from repository. Will clone ozzuworld/june."
        REPO_MODE=false
    fi
}

# Function to clone repository if needed
setup_repository() {
    if [ "$REPO_MODE" = false ]; then
        echo "📥 Cloning ozzuworld/june repository..."
        
        if [ -d "/opt/june" ]; then
            echo "🔄 Updating existing repository..."
            cd /opt/june
            git pull origin main
        else
            git clone https://github.com/ozzuworld/june.git /opt/june
            cd /opt/june
        fi
        
        REPO_PATH="/opt/june"
        
        # Make scripts executable
        chmod +x enhanced-k8s-bootstrap.sh 2>/dev/null || true
        chmod +x status-check.sh 2>/dev/null || true
        
        echo "✅ Repository ready at $REPO_PATH"
    fi
}

# Function to validate GitHub token EARLY
validate_github_token() {
    echo "🔍 Validating GitHub token..."
    
    # Test the token immediately
    local test_url="${GITHUB_REPO_URL}/actions/runners"
    local response=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        "$test_url" 2>/dev/null || echo "000")
    
    if [ "$response" = "200" ] || [ "$response" = "422" ]; then
        echo "✅ GitHub token is valid"
        return 0
    else
        echo "❌ GitHub token validation failed (HTTP $response)"
        echo ""
        echo "🔧 To fix this:"
        echo "1. Go to: https://github.com/ozzuworld/june/settings/actions/runners"
        echo "2. Click 'New self-hosted runner'"  
        echo "3. Copy the FRESH token (starts with 'A')"
        echo "4. Run this script again IMMEDIATELY"
        echo ""
        exit 1
    fi
}

# Function for cleanup on failure
cleanup_on_failure() {
    echo "🧹 Cleaning up failed installation..."
    
    # Don't clean up if we haven't installed anything yet
    if [ -z "$INSTALL_STARTED" ]; then
        echo "ℹ️  No cleanup needed (installation not started)"
        return
    fi
    
    # Stop and remove containers
    docker stop $(docker ps -aq) 2>/dev/null || true
    docker rm $(docker ps -aq) 2>/dev/null || true
    
    # Reset kubeadm
    kubeadm reset -f 2>/dev/null || true
    
    # Remove directories
    rm -rf /root/.kube /root/actions-runner 2>/dev/null || true
    
    echo "🗑️  Cleanup completed"
}

# Trap cleanup on script failure
trap cleanup_on_failure ERR

# Check repository status first
check_repository

# Get configuration from user FIRST (while token is fresh)
echo "📝 Configuration Setup (Token expires in 1 hour!)"
echo "=================================================="

prompt_input "Enter your GitHub repository URL" GITHUB_REPO_URL "https://github.com/ozzuworld/june"
echo ""
echo "⚠️  IMPORTANT: Get a FRESH GitHub Actions runner token!"
echo "1. Go to: https://github.com/ozzuworld/june/settings/actions/runners"
echo "2. Click 'New self-hosted runner'"
echo "3. Copy the token (starts with 'A') - it expires in 1 hour!"
echo ""
prompt_input "Enter your FRESH GitHub Actions runner token" GITHUB_TOKEN

# Validate token IMMEDIATELY
validate_github_token

prompt_input "Enter runner name" RUNNER_NAME "vast-ai-k8s-runner"
prompt_input "Enter additional runner labels (comma-separated)" RUNNER_LABELS "kubernetes,vast-ai,docker"
prompt_input "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"
prompt_input "Install as service? (y/n)" INSTALL_SERVICE "y"
prompt_input "Setup GPU support? (y/n)" SETUP_GPU "n"

echo ""
echo "🔍 Configuration Summary:"
echo "  Repository: $GITHUB_REPO_URL"
echo "  Runner Name: $RUNNER_NAME"
echo "  Runner Labels: $RUNNER_LABELS"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  Install as service: $INSTALL_SERVICE"
echo "  GPU Support: $SETUP_GPU"
echo ""

read -p "Continue with installation? (y/n): " confirm
if [[ $confirm != [yY] ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "🚀 Starting installation..."
INSTALL_STARTED=true

# Setup repository if needed
setup_repository

# STEP 1: Minimal system setup for GitHub runner (FAST!)
echo "📦 Installing essential packages..."
apt-get update
apt-get install -y curl wget git

# STEP 2: Install GitHub Actions Runner FIRST (while token is fresh!)
echo ""
echo "🏃 Installing GitHub Actions Runner (Priority: Token expires soon!)"
echo "=================================================================="

mkdir -p /root/actions-runner
cd /root/actions-runner

# Download runner (this is fast)
echo "📥 Downloading GitHub Actions Runner..."
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Install minimal dependencies for runner
echo "📦 Installing runner dependencies..."
apt-get install -y libicu-dev

# Try to install .NET (if it fails, we'll continue)
apt-get install -y dotnet-runtime-6.0 2>/dev/null || {
    echo "⚠️  .NET installation failed, will try alternative method later"
}

# Configure GitHub Actions Runner IMMEDIATELY
echo "⚙️  Configuring GitHub Actions Runner (using fresh token)..."
export RUNNER_ALLOW_RUNASROOT="1"

# Configure the runner with the fresh token
if ./config.sh --url "$GITHUB_REPO_URL" --token "$GITHUB_TOKEN" --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work --unattended; then
    echo "✅ GitHub Actions Runner configured successfully!"
    RUNNER_CONFIGURED=true
else
    echo "❌ Runner configuration failed!"
    echo "This usually means the token expired during system updates."
    echo "Get a new token and run the script again."
    exit 1
fi

# Install and start as service if requested
if [[ $INSTALL_SERVICE == [yY] ]]; then
    echo "🔧 Installing runner as service..."
    ./svc.sh install
    ./svc.sh start
    echo "✅ Runner service started!"
    RUNNER_RUNNING=true
else
    echo "⚠️  Runner configured but not started as service."
    echo "   Run './run.sh' to start manually"
    RUNNER_RUNNING=false
fi

# STEP 3: Now do the heavy installation (Kubernetes, Docker, etc.)
echo ""
echo "🔨 Now installing Kubernetes and dependencies (this takes time)..."
echo "================================================================="

# Complete system update
echo "📦 Completing system updates..."
apt-get upgrade -y

# Install remaining dependencies
echo "📦 Installing remaining dependencies..."
apt-get install -y apt-transport-https ca-certificates gnupg lsb-release jq

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

# Get IPs
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

# Install Flannel
echo "🌐 Installing Flannel network plugin..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Configure single-node cluster
echo "🔧 Configuring single-node cluster..."
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Setup RBAC for GitHub Actions
echo "🔐 Setting up GitHub Actions RBAC..."
kubectl create namespace ci-cd || true

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: github-actions
  namespace: ci-cd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: github-actions-deployment
rules:
- apiGroups: ["", "apps", "extensions", "networking.k8s.io"]
  resources: ["*"]
  verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: github-actions-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: github-actions-deployment
subjects:
- kind: ServiceAccount
  name: github-actions
  namespace: ci-cd
EOF

# Wait for cluster
echo "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

# Install remaining components
echo "🔧 Installing additional components..."

# GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt update && apt install gh -y

# Ingress Controller
echo "🌐 Installing NGINX Ingress Controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml

# GPU support if requested
if [[ $SETUP_GPU == [yY] ]] && command -v nvidia-smi &> /dev/null; then
    echo "🎮 Setting up GPU support..."
    kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.13.0/nvidia-device-plugin.yml
fi

# Print success message
echo ""
echo "🎉======================================================"
echo "✅ Installation Complete!"
echo "======================================================"
echo ""
echo "📋 Summary:"
echo "  • ✅ GitHub Actions runner configured FIRST (token-safe)"
if [ "$RUNNER_RUNNING" = true ]; then
    echo "  • ✅ Runner is running as a service"
else
    echo "  • ⚠️  Runner configured but not started"
fi
echo "  • ✅ Kubernetes cluster ready"
echo "  • ✅ Docker and containerd configured"
echo "  • ✅ NGINX Ingress Controller installed"
echo "  • ✅ GitHub Actions RBAC configured"
echo ""
echo "🌐 Your external IP: $EXTERNAL_IP"
echo ""
echo "🔧 Next Steps:"
echo "  1. Your runner should appear in GitHub repo settings"
echo "  2. Push code to trigger your first deployment"
echo "  3. Add your config files to the repository"
echo ""
echo "🔍 Quick Checks:"
echo "  • Runner status: systemctl status actions.runner.*"
echo "  • Cluster status: kubectl get nodes"
echo "  • All pods: kubectl get pods -A"
echo ""
echo "======================================================"