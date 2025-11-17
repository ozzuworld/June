#!/bin/bash
# Helper script to reset Ombi to fresh state
# Use this if Ombi setup fails or you want to reconfigure from scratch

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "==========================================="
echo "Ombi Reset Utility"
echo "==========================================="
echo ""

warn "This will delete all Ombi configuration and data!"
warn "You will need to re-run the setup wizard after this."
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Reset cancelled."
    exit 0
fi

echo ""
log "Resetting Ombi..."

# Delete config directory contents
log "Deleting Ombi configuration..."
kubectl exec -n june-services deployment/ombi -- rm -rf /config/* 2>/dev/null || \
    warn "Could not delete config from pod (may not exist yet)"

# Also delete from host if accessible
if [ -d "/mnt/ssd/media-configs/ombi" ]; then
    log "Deleting host config directory..."
    rm -rf /mnt/ssd/media-configs/ombi/*
    success "Host config cleared"
fi

# Restart Ombi pod
log "Restarting Ombi deployment..."
kubectl rollout restart -n june-services deployment/ombi

log "Waiting for Ombi to restart..."
kubectl rollout status -n june-services deployment/ombi --timeout=120s

success "Ombi has been reset!"
echo ""
echo "Next steps:"
echo "  1. Wait 30 seconds for Ombi to fully initialize"
echo "  2. Re-run the setup script:"
echo "     python3 scripts/automation-media-stack/setup-ombi-wizard.py \\"
echo "       --url https://ombi.YOUR_DOMAIN \\"
echo "       --username admin \\"
echo "       --password YOUR_PASSWORD"
echo ""
echo "  Or access manually at: https://ombi.YOUR_DOMAIN"
echo ""
