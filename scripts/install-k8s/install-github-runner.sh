#!/bin/bash
# GitHub Actions Runner Installation
# Sets up self-hosted runner with proper permissions
# Usage: ./install-github-runner.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

echo "======================================================"
echo "🐙 GitHub Actions Runner Setup"
echo "======================================================"
echo ""

# Collect configuration
read -p "GitHub repository URL: " GITHUB_REPO_URL
if [ -z "$GITHUB_REPO_URL" ]; then
    log_error "Repository URL is required!"
    exit 1
fi

echo ""
echo "Get a fresh token from:"
echo "$GITHUB_REPO_URL/settings/actions/runners/new"
echo ""
read -p "GitHub runner token: " GITHUB_TOKEN

if [ -z "$GITHUB_TOKEN" ]; then
    log_error "Token is required!"
    exit 1
fi

read -p "Runner name [june-runner-$(hostname)]: " RUNNER_NAME
RUNNER_NAME=${RUNNER_NAME:-june-runner-$(hostname)}

# Install dependencies
log_info "Installing dependencies..."
apt-get update -qq
apt-get install -y libicu-dev

# Setup runner directory
RUNNER_DIR="/opt/actions-runner"
log_info "Setting up runner in $RUNNER_DIR..."
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Download latest runner
log_info "Downloading GitHub Actions runner..."
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep tag_name | cut -d '"' -f 4 | sed 's/v//')
log_info "Version: $RUNNER_VERSION"

curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

# Set permissions
chown -R root:root "$RUNNER_DIR"
chmod -R 755 "$RUNNER_DIR"

# Create necessary directories
mkdir -p "$RUNNER_DIR/_diag"
mkdir -p "$RUNNER_DIR/_work"
chmod 777 "$RUNNER_DIR/_diag"

# Create environment file
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

# Install service
log_info "Installing as system service..."
./svc.sh install root

# Create service override
RUNNER_SERVICE=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
if [ -n "$RUNNER_SERVICE" ]; then
    log_info "Creating service override..."
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
fi

# Start service
log_info "Starting runner service..."
./svc.sh start

# Verify
sleep 5
if systemctl is-active --quiet "actions.runner.*"; then
    log_success "GitHub Actions Runner is running!"
else
    log_error "Runner failed to start"
    journalctl -u "actions.runner.*" -n 50 --no-pager
    exit 1
fi

echo ""
echo "======================================================"
log_success "GitHub Actions Runner Setup Complete!"
echo "======================================================"
echo ""
echo "✅ Runner Configuration:"
echo "  Repository: $GITHUB_REPO_URL"
echo "  Runner Name: $RUNNER_NAME"
echo "  Directory: $RUNNER_DIR"
echo "  Labels: self-hosted, kubernetes, Linux, X64"
echo ""
echo "🔍 Verify runner registration:"
echo "  $GITHUB_REPO_URL/settings/actions/runners"
echo ""
echo "📋 Useful Commands:"
echo "  Status:  cd $RUNNER_DIR && sudo ./svc.sh status"
echo "  Logs:    journalctl -u actions.runner.* -f"
echo "  Restart: cd $RUNNER_DIR && sudo ./svc.sh restart"
echo "  Stop:    cd $RUNNER_DIR && sudo ./svc.sh stop"
echo ""
echo "======================================================"