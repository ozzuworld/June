#!/bin/bash
# Phase 11: Deploy Headscale VPN Control Plane
# Headscale provides a self-hosted Tailscale-compatible control plane

set -e

source "$(dirname "$0")/../common/common.sh"

ROOT_DIR="$1"
if [ -z "$ROOT_DIR" ]; then
    error "Root directory not provided"
fi

log "Starting Headscale VPN Control Plane deployment..."

# Load configuration
source "$ROOT_DIR/config.env"

# Validate required variables
if [ -z "$DOMAIN" ]; then
    error "DOMAIN must be set in config.env"
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    error "kubectl is not installed or not in PATH"
fi

# Check if cluster is accessible
if ! kubectl cluster-info &>/dev/null; then
    error "Cannot connect to Kubernetes cluster"
fi

log "Deploying Headscale to Kubernetes..."

# Create temporary file with domain substitution
TEMP_HEADSCALE_YAML=$(mktemp)
trap "rm -f $TEMP_HEADSCALE_YAML" EXIT

# Replace domain placeholders in the headscale configuration
cat "$ROOT_DIR/k8s/headscale/headscale-all.yaml" | \
    sed "s/ozzu\.world/$DOMAIN/g" | \
    sed "s/headscale\.ozzu\.world/headscale.$DOMAIN/g" | \
    sed "s/tail\.ozzu\.world/tail.$DOMAIN/g" | \
    sed "s/ozzu-world-wildcard-tls/${DOMAIN//\./-}-wildcard-tls/g" > "$TEMP_HEADSCALE_YAML"

# Apply the Headscale deployment
log "Creating Headscale namespace and resources..."
kubectl apply -f "$TEMP_HEADSCALE_YAML"

# Wait for deployment to be ready
log "Waiting for Headscale deployment to be ready..."
if ! kubectl wait --for=condition=available --timeout=300s deployment/headscale -n headscale; then
    warn "Headscale deployment not ready after 5 minutes, checking status..."
    kubectl get pods -n headscale
    kubectl describe deployment/headscale -n headscale
fi

# Wait for the certificate copy job to complete
log "Waiting for wildcard certificate to be copied..."
if kubectl get job copy-wildcard-cert -n headscale &>/dev/null; then
    kubectl wait --for=condition=complete --timeout=120s job/copy-wildcard-cert -n headscale || {
        warn "Certificate copy job did not complete successfully"
        kubectl logs job/copy-wildcard-cert -n headscale || true
    }
fi

# Check if Headscale is accessible
log "Verifying Headscale deployment..."
HEADSCALE_POD=$(kubectl get pods -n headscale -l app=headscale -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -n "$HEADSCALE_POD" ]; then
    log "Headscale pod: $HEADSCALE_POD"
    
    # Check if headscale binary is working
    if kubectl exec -n headscale "$HEADSCALE_POD" -- headscale --version &>/dev/null; then
        success "Headscale binary is working correctly"
    else
        warn "Headscale binary check failed, but container is running"
    fi
else
    error "No Headscale pod found"
fi

# Show deployment status
echo ""
log "=== Headscale Deployment Status ==="
echo ""
echo "📋 Namespace Resources:"
kubectl get all -n headscale

echo ""
echo "🔐 TLS Certificate:"
kubectl get secret -n headscale | grep tls || echo "No TLS secrets found"

echo ""
echo "🌐 Ingress Configuration:"
kubectl get ingress -n headscale

echo ""
echo "📊 Service Status:"
kubectl get svc -n headscale

echo ""
log "=== Headscale Management Commands ==="
echo ""
echo "# Create a user namespace:"
echo "kubectl exec -n headscale deployment/headscale -- headscale users create june-team"
echo ""
echo "# Generate pre-auth key for device registration:"
echo "kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create --user june-team --expiration 24h"
echo ""
echo "# List connected devices:"
echo "kubectl exec -n headscale deployment/headscale -- headscale nodes list"
echo ""
echo "# View logs:"
echo "kubectl logs -n headscale deployment/headscale -f"

echo ""
success "Headscale VPN Control Plane deployment completed!"

echo ""
log "=== Access Information ==="
echo "  Headscale URL: https://headscale.$DOMAIN"
echo "  Tailscale Domain: tail.$DOMAIN"
echo "  Network Range: 100.64.0.0/10"
echo ""
echo "📱 To connect devices:"
echo "  1. Install Tailscale client on your device"
echo "  2. Create a user: kubectl exec -n headscale deployment/headscale -- headscale users create myuser"
echo "  3. Generate auth key: kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create --user myuser"
echo "  4. Connect: tailscale up --login-server https://headscale.$DOMAIN --authkey [KEY]"
echo ""