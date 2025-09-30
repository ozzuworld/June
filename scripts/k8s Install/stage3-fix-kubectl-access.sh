#!/bin/bash
# Fix kubectl access for GitHub Actions runner

echo "🔧 Fixing kubectl access for GitHub Actions runner"
echo "================================================="

# Check if Kubernetes is running
if ! kubectl get nodes &>/dev/null; then
    echo "❌ Kubernetes cluster is not accessible"
    echo "Please ensure your Kubernetes cluster is running"
    exit 1
fi

echo "✅ Kubernetes cluster is accessible"

# Find the GitHub Actions runner user
RUNNER_USER="actions-runner"
if ! id "$RUNNER_USER" &>/dev/null; then
    RUNNER_USER="root"
    echo "ℹ️ Using root user for runner"
else
    echo "ℹ️ Found actions-runner user"
fi

# Get runner home directory
if [ "$RUNNER_USER" = "root" ]; then
    RUNNER_HOME="/root"
else
    RUNNER_HOME="/home/$RUNNER_USER"
fi

echo "📁 Runner home directory: $RUNNER_HOME"

# Create .kube directory for runner
echo "📂 Creating .kube directory..."
mkdir -p "$RUNNER_HOME/.kube"

# Copy kubeconfig
echo "📋 Copying kubeconfig..."
cp /root/.kube/config "$RUNNER_HOME/.kube/config"

# Fix permissions
echo "🔐 Fixing permissions..."
if [ "$RUNNER_USER" != "root" ]; then
    chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME/.kube"
else
    chmod 600 "$RUNNER_HOME/.kube/config"
fi

# Test kubectl access
echo "🧪 Testing kubectl access..."
if [ "$RUNNER_USER" != "root" ]; then
    sudo -u "$RUNNER_USER" kubectl get nodes
else
    kubectl get nodes
fi

echo "✅ kubectl access fixed for GitHub Actions runner!"
echo ""
echo "🔧 Next steps:"
echo "1. Restart GitHub Actions runner: systemctl restart actions.runner.*"
echo "2. Test your workflow again"