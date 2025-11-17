#!/bin/bash
# Remove LiveKit routing from June platform ingress
# This fixes the conflict with the new LiveKit ingress in media-stack namespace

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
else
    error "config.env not found"
fi

log "Removing LiveKit routing from June platform ingress..."

# Check if June platform is installed
if ! helm list -n june-services | grep -q june-platform; then
    error "June platform not installed in june-services namespace"
fi

# Upgrade June platform to apply the new ingress template (without LiveKit)
log "Upgrading June platform Helm release..."
helm upgrade june-platform "${ROOT_DIR}/helm/june-platform" \
    --namespace june-services \
    --reuse-values \
    --wait \
    --timeout 5m

success "June platform ingress updated!"
echo ""
echo "✅ LiveKit routing removed from june-ingress"
echo "✅ livekit.ozzu.world is now available for media-stack namespace"
echo ""
echo "You can now continue the installation:"
echo "   sudo ./scripts/install/webrtc/02-livekit.sh"
echo ""
