#!/bin/bash
# Deploy GPU services using SkyPilot

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $*"; }
success() { echo -e "${GREEN}✅${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️${NC} $*"; }

# Load configuration
if [ -f "config.env" ]; then
    source config.env
else
    echo "Error: config.env not found"
    exit 1
fi

log "Deploying June GPU services via SkyPilot..."

# Check prerequisites
if ! command -v sky &> /dev/null; then
    log "Installing SkyPilot..."
    if command -v pip3 &>/dev/null; then
        pip3 install "skypilot[vast]" --break-system-packages
    else
        python3 -m pip install "skypilot[vast]" --break-system-packages
    fi
fi

# Setup Vast.ai credentials (Sky expects ~/.config/vastai/vast_api_key)
if [ -z "$VAST_API_KEY" ]; then
    echo "Error: VAST_API_KEY not set in config.env"
    exit 1
fi
mkdir -p ~/.config/vastai
printf "%s" "$VAST_API_KEY" > ~/.config/vastai/vast_api_key
chmod 600 ~/.config/vastai/vast_api_key

# Validate Vast
sky check vast || warn "Vast check reported issues; continuing"

# Get Headscale auth key
log "Getting Headscale authentication key..."
HEADSCALE_KEY=$(kubectl -n headscale exec deploy/headscale -- \
    headscale preauthkeys create --user ozzu --reusable --expiration 24h 2>/dev/null | tail -1)

if [ -z "$HEADSCALE_KEY" ]; then
    warn "Failed to get Headscale auth key; continuing without VPN"
else
    export HEADSCALE_AUTH_KEY="$HEADSCALE_KEY"
fi

# Export environment variables for SkyPilot
export ORCHESTRATOR_URL="http://june-orchestrator.june-services.svc.cluster.local:8080"
export LIVEKIT_URL="http://livekit-livekit-server.june-services.svc.cluster.local:7880"

# Launch GPU services
log "Launching GPU services on Vast.ai..."
# --detach-setup flag no longer exists; use --detach-run for background run, and rely on cache for setup
sky launch k8s/skypilot/gpu-workloads/june-gpu-services.yaml \
    --cloud vast \
    --gpus RTX4060:1 \
    --retry-until-up \
    --detach-run

success "GPU services deployment initiated"

# Show status
log "Checking deployment status..."
sky status --all || true

echo ""
log "📋 Management Commands:"
echo "  sky status                                # Check all instances"
echo "  sky logs june-gpu-services -f             # Follow service logs"
echo "  sky exec june-gpu-services 'nvidia-smi'    # Run commands"
echo "  sky down june-gpu-services                # Stop instance"
echo "  sky stop june-gpu-services                # Pause instance"
echo ""

success "Deployment complete! GPU services are starting..."