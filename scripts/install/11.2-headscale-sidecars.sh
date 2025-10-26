#!/bin/bash
# June Platform - Phase 11.2: Deploy Tailscale Sidecars for Headscale
# Integrates Tailscale sidecars with existing June Platform deployment

set -e

source "$(dirname "$0")/../common/logging.sh"

# Get absolute path to avoid relative path issues
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Validate ROOT_DIR exists and has expected structure
if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Current: $ROOT_DIR"
    error "Please run from June project directory or pass ROOT_DIR as argument"
    exit 1
fi

log "Using ROOT_DIR: $ROOT_DIR"

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

# Check if Headscale is enabled in configuration
if [ -z "$HEADSCALE_DOMAIN" ] && [ "$ENABLE_TAILSCALE_SIDECARS" != "true" ]; then
    warn "Headscale not configured or Tailscale sidecars disabled, skipping..."
    log "To enable: set HEADSCALE_DOMAIN=headscale.ozzu.world and ENABLE_TAILSCALE_SIDECARS=true in config.env"
    exit 0
fi

# Check if Headscale is already deployed
if ! kubectl get namespace headscale &>/dev/null; then
    warn "Headscale namespace not found. Please run phase 11-headscale first"
    log "Skipping Tailscale sidecars deployment"
    exit 0
fi

log "Phase 11.2/12: Deploying Tailscale sidecars for June services..."

# Check if June Platform is already deployed
if ! helm list -n june-services | grep -q june-platform; then
    warn "June Platform not found. Please run phase 09-june-platform first"
    log "Skipping Tailscale sidecars deployment"
    exit 0
fi

# Run the sidecar deployment script
log "Running Headscale sidecar deployment script..."
if bash "$ROOT_DIR/scripts/deploy-headscale-sidecars.sh"; then
    success "Tailscale sidecars deployed successfully"
else
    error "Failed to deploy Tailscale sidecars"
    exit 1
fi

# Verify deployment
log "Verifying Tailscale sidecar deployment..."
sleep 10  # Give sidecars time to start

# Check if sidecars are running
for deployment in june-orchestrator june-idp; do
    if kubectl get deployment "$deployment" -n june-services &>/dev/null; then
        SIDECAR_COUNT=$(kubectl get deployment "$deployment" -n june-services -o jsonpath='{.spec.template.spec.containers[*].name}' | grep -c tailscale || echo "0")
        if [ "$SIDECAR_COUNT" -gt 0 ]; then
            log "✓ $deployment has Tailscale sidecar"
        else
            warn "✗ $deployment missing Tailscale sidecar"
        fi
    else
        warn "✗ $deployment not found"
    fi
done

# Check Headscale node registration
log "Checking Headscale node registrations..."
if kubectl -n headscale exec deployment/headscale -c headscale -- headscale nodes list | grep -q june-orchestrator; then
    log "✓ june-orchestrator registered with Headscale"
else
    warn "✗ june-orchestrator not registered with Headscale yet (may take a few minutes)"
fi

if kubectl -n headscale exec deployment/headscale -c headscale -- headscale nodes list | grep -q june-idp; then
    log "✓ june-idp registered with Headscale"
else
    warn "✗ june-idp not registered with Headscale yet (may take a few minutes)"
fi

success "Tailscale sidecars deployment phase completed"

log "Services are now accessible via:"
log "  • Tailnet: june-orchestrator.tail.ozzu.world, june-idp.tail.ozzu.world"
log "  • Public: api.ozzu.world, idp.ozzu.world (unchanged)"
log "  • Internal: june-orchestrator.june-services.svc.cluster.local (unchanged)"