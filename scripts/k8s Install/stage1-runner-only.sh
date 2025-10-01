#!/bin/bash
# Stage 1: GitHub Runner (Fixed Permissions)

echo "🏃 Stage 1: GitHub Actions Runner Setup"
echo "========================================"

read -p "Enter GitHub repository URL: " REPO_URL
echo "Get token from: ${REPO_URL}/settings/actions/runners/new"
read -p "Enter FRESH GitHub token: " TOKEN
read -p "Enter runner name [quick-runner]: " RUNNER_NAME
RUNNER_NAME=${RUNNER_NAME:-quick-runner}

# Install dependencies
apt-get update
apt-get install -y curl wget git libicu-dev

# Setup runner in proper location
RUNNER_DIR="/opt/actions-runner"
mkdir -p $RUNNER_DIR
cd $RUNNER_DIR

# Download runner
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf actions-runner.tar.gz

# Configure
export RUNNER_ALLOW_RUNASROOT="1"
./config.sh --url "$REPO_URL" --token "$TOKEN" --name "$RUNNER_NAME" \
  --labels "kubernetes,stage1" --work _work --unattended

# Install and start service
./svc.sh install
./svc.sh start

echo ""
echo "✅ Stage 1 Complete!"
echo "📊 Check status: cd $RUNNER_DIR && sudo ./svc.sh status"
echo "📋 Next: Run Stage 2 for Kubernetes installation"