#!/bin/bash
# Stage 1: GitHub Runner Setup (Fixed Permissions)
# Location: June/scripts/k8s Install/stage1-runner-only.sh

set -e

echo "🏃 Stage 1: GitHub Actions Runner Setup"
echo "========================================"

read -p "Enter GitHub repository URL: " REPO_URL
echo "Get token from: ${REPO_URL}/settings/actions/runners/new"
read -p "Enter FRESH GitHub token: " TOKEN
read -p "Enter runner name [quick-runner]: " RUNNER_NAME
RUNNER_NAME=${RUNNER_NAME:-quick-runner}

# Install dependencies
echo "📦 Installing dependencies..."
apt-get update -qq
apt-get install -y curl wget git libicu-dev

# Setup runner in proper location
RUNNER_DIR="/opt/actions-runner"
echo "📁 Setting up runner in $RUNNER_DIR..."
mkdir -p $RUNNER_DIR
cd $RUNNER_DIR

# Download latest runner
echo "⬇️  Downloading GitHub Actions runner..."
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep tag_name | cut -d '"' -f 4 | sed 's/v//')
echo "   Version: $RUNNER_VERSION"
curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

# FIX: Set proper permissions
echo "🔐 Setting up permissions..."
chown -R root:root "$RUNNER_DIR"
chmod -R 755 "$RUNNER_DIR"

# FIX: Create _diag directory with proper permissions (prevents log file errors)
mkdir -p "$RUNNER_DIR/_diag"
chmod 777 "$RUNNER_DIR/_diag"
echo "✅ Created _diag directory with proper permissions"

# FIX: Create _work directory
mkdir -p "$RUNNER_DIR/_work"
chmod 755 "$RUNNER_DIR/_work"

# FIX: Create environment file with proper configuration
echo "📝 Creating environment configuration..."
cat > "$RUNNER_DIR/.env" << 'EOF'
RUNNER_ALLOW_RUNASROOT="1"
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF

# Configure runner
echo "⚙️  Configuring runner..."
export RUNNER_ALLOW_RUNASROOT="1"

./config.sh \
    --url "$REPO_URL" \
    --token "$TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "self-hosted,kubernetes,Linux,X64" \
    --work "_work" \
    --unattended \
    --replace

# Install service as root
echo "🔧 Installing as system service..."
./svc.sh install root

# FIX: Create systemd service override for proper environment
RUNNER_SERVICE=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
if [ -n "$RUNNER_SERVICE" ]; then
    echo "🔧 Creating service override for reliability..."
    mkdir -p "/etc/systemd/system/${RUNNER_SERVICE}.d"
    
    cat > "/etc/systemd/system/${RUNNER_SERVICE}.d/override.conf" << EOF
[Service]
# Run as root for full system access
User=root
Group=root

# Environment variables
Environment="RUNNER_ALLOW_RUNASROOT=1"
Environment="KUBECONFIG=/root/.kube/config"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Working directory
WorkingDirectory=${RUNNER_DIR}

# Permissions
UMask=0022

# Logging
StandardOutput=journal
StandardError=journal

# Allow core dumps for debugging
LimitCORE=infinity
EOF

    systemctl daemon-reload
    echo "✅ Service configuration created"
fi

# Start the service
echo "▶️  Starting runner service..."
./svc.sh start

# Wait and verify
sleep 5

echo ""
echo "✅ Stage 1 Complete!"
echo ""
echo "📊 Runner Status:"
./svc.sh status

echo ""
echo "🔍 Verify runner connected on GitHub:"
echo "   ${REPO_URL}/settings/actions/runners"
echo ""
echo "📋 View logs:"
echo "   journalctl -u actions.runner.* -f"
echo ""
echo "🔧 Useful commands:"
echo "   Status: cd $RUNNER_DIR && sudo ./svc.sh status"
echo "   Logs:   journalctl -u actions.runner.* -f"
echo "   Stop:   cd $RUNNER_DIR && sudo ./svc.sh stop"
echo "   Start:  cd $RUNNER_DIR && sudo ./svc.sh start"
echo ""
echo "📋 Next: Run stage2 for Kubernetes installation"

# Show initial logs to verify it's working
echo ""
echo "📋 Initial logs (checking for errors):"
journalctl -u actions.runner.* --no-pager -n 20 || echo "Logs not available yet"