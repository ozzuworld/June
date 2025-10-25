#!/bin/bash
# Phase 12: Deploy SkyPilot for Vast.ai GPU orchestration

set -e

source "$(dirname "$0")/../common/common.sh"

ROOT_DIR="$1"
if [ -z "$ROOT_DIR" ]; then
    error "Root directory not provided"
fi

log "Starting SkyPilot installation for Vast.ai integration..."

# Load configuration
source "$ROOT_DIR/config.env"

# Check for Vast.ai API key
if [ -z "$VAST_API_KEY" ]; then
    warn "VAST_API_KEY not set in config.env"
    echo ""
    echo "To enable Vast.ai GPU provider:"
    echo "  1. Get API key from https://console.vast.ai/"
    echo "  2. Add to config.env: VAST_API_KEY=your_key"
    echo ""
    log "Skipping SkyPilot deployment (no API key)"
    exit 0
fi

log "Installing SkyPilot..."

# Ensure Python and pip are available - Ubuntu 24.04 compatible
install_python_pip() {
    log "Setting up Python and pip..."
    
    # Install Python if missing
    if ! command -v python3 &> /dev/null; then
        log "Installing Python3..."
        apt-get update
        apt-get install -y python3
    fi
    
    # Check if pip is already working
    if python3 -m pip --version &>/dev/null; then
        log "pip is already available"
        return 0
    fi
    
    # Try installing pip via package manager first
    log "Attempting to install pip via package manager..."
    apt-get update
    # Install what's available (python3-pip works on older Ubuntu, python3-setuptools on newer)
    apt-get install -y python3-setuptools python3-venv 2>/dev/null || true
    apt-get install -y python3-pip 2>/dev/null || true
    
    # Check if pip works now
    if python3 -m pip --version &>/dev/null; then
        log "pip installed via package manager"
        return 0
    fi
    
    # Try ensurepip (built into Python)
    log "Attempting to bootstrap pip with ensurepip..."
    if python3 -m ensurepip --upgrade --default-pip &>/dev/null; then
        log "pip bootstrapped with ensurepip"
        return 0
    fi
    
    # If ensurepip fails, try with --break-system-packages (needed on some systems)
    if python3 -m ensurepip --upgrade --default-pip --break-system-packages &>/dev/null; then
        log "pip bootstrapped with ensurepip (break-system-packages)"
        return 0
    fi
    
    # Final fallback: download and run get-pip.py
    log "Bootstrapping pip with get-pip.py..."
    if command -v curl &>/dev/null; then
        curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    elif command -v wget &>/dev/null; then
        wget -qO /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
    else
        error "Neither curl nor wget available to download get-pip.py"
    fi
    
    python3 /tmp/get-pip.py
    rm -f /tmp/get-pip.py
    
    # Final verification
    if python3 -m pip --version &>/dev/null; then
        log "pip bootstrapped successfully with get-pip.py"
    else
        error "Failed to install pip after trying all methods"
    fi
}

# Install Python and pip
install_python_pip

# Install SkyPilot on the host (for management)
if ! command -v sky &> /dev/null; then
    log "Installing SkyPilot with Vast.ai support..."
    
    # Try different pip commands in order of preference
    if command -v pip3 &> /dev/null; then
        pip3 install "skypilot[vast]" --break-system-packages
    elif command -v pip &> /dev/null; then
        pip install "skypilot[vast]" --break-system-packages
    else
        python3 -m pip install "skypilot[vast]" --break-system-packages
    fi
    
    # Verify installation
    if command -v sky &> /dev/null; then
        success "SkyPilot installed successfully"
    else
        error "SkyPilot installation failed - sky command not found"
    fi
else
    log "SkyPilot already installed"
fi

# Setup Vast.ai credentials
log "Setting up Vast.ai credentials..."
echo "$VAST_API_KEY" > ~/.vast_api_key
chmod 600 ~/.vast_api_key

# Verify Vast.ai connectivity
log "Verifying Vast.ai connectivity..."
if sky check vast &>/dev/null; then
    success "Vast.ai connectivity verified"
else
    warn "Failed to connect to Vast.ai API (this may be normal if no instances are running)"
fi

# Get Headscale auth key
log "Getting Headscale authentication key..."
if kubectl get namespace headscale &>/dev/null; then
    HEADSCALE_KEY=$(kubectl -n headscale exec deploy/headscale -- \
        headscale preauthkeys create --user ozzu --reusable --expiration 168h 2>/dev/null | tail -1)
    
    if [ -n "$HEADSCALE_KEY" ]; then
        success "Headscale auth key obtained"
    else
        warn "Failed to get Headscale auth key (continuing without VPN)"
        HEADSCALE_KEY=""
    fi
else
    log "Headscale not installed, skipping VPN setup"
    HEADSCALE_KEY=""
fi

# Create SkyPilot namespace and secrets in Kubernetes
log "Creating Kubernetes resources..."
kubectl create namespace skypilot-system --dry-run=client -o yaml | kubectl apply -f -

# Create secret with credentials
kubectl create secret generic skypilot-credentials \
    --from-literal=vast-api-key="$VAST_API_KEY" \
    --from-literal=headscale-auth-key="$HEADSCALE_KEY" \
    -n skypilot-system \
    --dry-run=client -o yaml | kubectl apply -f -

success "SkyPilot credentials configured"

# Deploy SkyPilot controller (optional - for K8s-managed workflows)
if [ -f "$ROOT_DIR/k8s/skypilot/skypilot-controller.yaml" ]; then
    log "Deploying SkyPilot controller..."
    kubectl apply -f "$ROOT_DIR/k8s/skypilot/skypilot-controller.yaml"
else
    log "SkyPilot controller manifest not found, skipping K8s deployment"
fi

echo ""
log "=== SkyPilot Installation Complete ==="
echo ""
echo "✅ SkyPilot installed and configured"
echo "✅ Vast.ai credentials set up"
if [ -n "$HEADSCALE_KEY" ]; then
    echo "✅ Headscale VPN integration ready"
fi
echo ""
echo "📋 Next Steps:"
echo "  1. Deploy GPU services:"
echo "     ./scripts/skypilot/deploy-gpu-services.sh"
echo ""
echo "  2. Check status:"
echo "     sky status --all"
echo ""
echo "  3. View logs:"
echo "     sky logs june-gpu-services -f"
echo ""
echo "📚 SkyPilot Documentation:"
echo "   https://docs.skypilot.co"
echo ""

success "Phase 12: SkyPilot installation completed"