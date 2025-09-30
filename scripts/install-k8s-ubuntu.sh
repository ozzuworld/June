#!/bin/bash
# Kubernetes + GitHub Actions Runner Setup Script for Vast.ai
# Fixed for container runtime and removed proxy

set -e

echo "======================================================"
echo "🚀 Kubernetes + GitHub Actions Runner Setup Script"
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

# Get configuration from user
echo "📝 Configuration Setup"
echo "----------------------"

prompt_input "Enter your GitHub repository URL (e.g., https://github.com/username/repo)" GITHUB_REPO_URL
prompt_input "Enter your GitHub Actions runner token" GITHUB_TOKEN
prompt_input "Enter runner name" RUNNER_NAME "vast-ai-k8s-runner"
prompt_input "Enter additional runner labels (comma-separated)" RUNNER_LABELS "kubernetes,vast-ai,docker"
prompt_input "Pod network CIDR" POD_NETWORK_CIDR "10.244.0.0/16"
prompt_input "Install as service? (y/n)" INSTALL_SERVICE "y"

echo ""
echo "🔍 Configuration Summary:"
echo "  Repository: $GITHUB_REPO_URL"
echo "  Runner Name: $RUNNER_NAME"
echo "  Runner Labels: $RUNNER_LABELS"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  Install as service: $INSTALL_SERVICE"
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
apt-get install -y curl wget apt-transport-https ca-certificates gnupg lsb-release

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

# Create CI/CD namespace and RBAC
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
---
apiVersion: v1
kind: Secret
type: kubernetes.io/service-account-token
metadata:
  name: github-actions-token
  namespace: ci-cd
  annotations:
    kubernetes.io/service-account.name: github-actions
EOF

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

# Install GitHub Actions Runner
echo "🏃 Installing GitHub Actions Runner..."
cd /root
mkdir -p actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Install .NET dependencies for runner
echo "📦 Installing .NET dependencies..."
apt-get install -y libicu-dev dotnet-runtime-6.0

# Configure GitHub Actions Runner
echo "⚙️  Configuring GitHub Actions Runner..."
export RUNNER_ALLOW_RUNASROOT="1"
./config.sh --url "$GITHUB_REPO_URL" --token "$GITHUB_TOKEN" --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work --unattended

# Install and start as service if requested
if [[ $INSTALL_SERVICE == [yY] ]]; then
    echo "🔧 Installing runner as service..."
    ./svc.sh install
    ./svc.sh start
    echo "✅ Runner service started!"
else
    echo "⚠️  Runner installed but not started as service."
    echo "   Run './run.sh' to start manually"
fi

# Create sample workflow
echo "📄 Creating sample workflow..."
mkdir -p /tmp/sample-workflow
cat > /tmp/sample-workflow/deploy.yml << 'EOF'
name: Deploy to Kubernetes

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: self-hosted
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Show cluster info
      run: |
        echo "🎯 Kubernetes Cluster Info:"
        kubectl cluster-info
        echo "📊 Node Status:"
        kubectl get nodes -o wide
        echo "🏃 Pods Status:"
        kubectl get pods -A
    
    - name: Deploy sample app (uncomment to use)
      run: |
        # kubectl apply -f k8s/
        echo "Add your deployment commands here"
EOF

# Print final information
echo ""
echo "🎉======================================================"
echo "✅ Installation Complete!"
echo "======================================================"
echo ""
echo "📋 Summary:"
echo "  • Kubernetes cluster initialized and ready"
echo "  • GitHub Actions runner installed and running"
echo "  • Direct cluster access (no proxy needed)"
echo ""
echo "🔧 Next Steps:"
echo "  1. Copy the sample workflow from /tmp/sample-workflow/deploy.yml"
echo "  2. Add it to your repo as .github/workflows/deploy.yml"
echo "  3. Create your Kubernetes manifests in k8s/ directory"
echo "  4. Push to trigger your first deployment!"
echo ""
echo "🔍 Useful Commands:"
echo "  • Check runner status: systemctl status actions.runner.*"
echo "  • View cluster: kubectl get all -A"
echo "  • Runner logs: journalctl -u actions.runner.* -f"
echo ""
echo "🌐 Your external IP: $EXTERNAL_IP"
echo ""
echo "======================================================"
