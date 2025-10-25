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

# Install SkyPilot on the host (for management)
if ! command -v sky &> /dev/null; then
    pip install "skypilot[vast]" --break-system-packages
fi

# Setup Vast.ai credentials
echo "$VAST_API_KEY" > ~/.vast_api_key
chmod 600 ~/.vast_api_key

# Verify Vast.ai connectivity
log "Verifying Vast.ai connectivity..."
if sky check vast &>/dev/null; then
    success "Vast.ai connectivity verified"
else
    error "Failed to connect to Vast.ai API"
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