#!/bin/bash
# Stage 1: GitHub Runner Only (Fast - 2-3 minutes)

echo "🏃 Stage 1: GitHub Actions Runner Setup (FAST!)"
echo "=============================================="

# Get fresh token
read -p "Enter GitHub repository URL: " REPO_URL
echo "Get fresh token from: ${REPO_URL}/settings/actions/runners"
read -p "Enter FRESH GitHub token: " TOKEN
read -p "Enter runner name [quick-runner]: " RUNNER_NAME
RUNNER_NAME=${RUNNER_NAME:-quick-runner}

# Minimal install
apt-get update
apt-get install -y curl wget git libicu-dev

# Setup runner
mkdir -p /root/actions-runner
cd /root/actions-runner
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf actions-runner.tar.gz

# Configure with fresh token
export RUNNER_ALLOW_RUNASROOT="1"
./config.sh --url "$REPO_URL" --token "$TOKEN" --name "$RUNNER_NAME" --labels "kubernetes,stage1" --work _work --unattended

# Start runner
./svc.sh install && ./svc.sh start

echo "✅ Stage 1 Complete! Runner is connected."
echo "📋 Now run Stage 2 to install Kubernetes:"
echo "   sudo ./stage2-k8s-install.sh"