#!/bin/bash
# Phase 11: Deploy Headscale VPN Control Plane (hardened TLS copy verification)

set -e

source "$(dirname "$0")/../common/common.sh"

ROOT_DIR="$1"
if [ -z "$ROOT_DIR" ]; then
    error "Root directory not provided"
fi

log "Starting Headscale VPN Control Plane deployment..."

source "$ROOT_DIR/config.env"

if [ -z "$DOMAIN" ]; then
    error "DOMAIN must be set in config.env"
fi

check_command kubectl "Please install kubectl"
if ! kubectl cluster-info &>/dev/null; then
    error "Cannot connect to Kubernetes cluster"
fi

log "Deploying Headscale to Kubernetes..."
TEMP_HEADSCALE_YAML=$(mktemp)
trap "rm -f $TEMP_HEADSCALE_YAML" EXIT

cat "$ROOT_DIR/k8s/headscale/headscale-all.yaml" | \
    sed "s/ozzu\.world/$DOMAIN/g" | \
    sed "s/headscale\.ozzu\.world/headscale.$DOMAIN/g" | \
    sed "s/tail\.ozzu\.world/tail.$DOMAIN/g" | \
    sed "s/ozzu-world-wildcard-tls/${DOMAIN//\./-}-wildcard-tls/g" > "$TEMP_HEADSCALE_YAML"

log "Creating Headscale namespace and resources..."
kubectl apply -f "$TEMP_HEADSCALE_YAML"

log "Waiting for Headscale deployment to be ready..."
if ! kubectl wait --for=condition=available --timeout=300s deployment/headscale -n headscale; then
    warn "Headscale deployment not ready after 5 minutes, checking status..."
    kubectl get pods -n headscale
    kubectl describe deployment/headscale -n headscale
fi

log "Waiting for wildcard certificate to be copied..."
if kubectl get job copy-wildcard-cert -n headscale &>/dev/null; then
    kubectl wait --for=condition=complete --timeout=180s job/copy-wildcard-cert -n headscale || {
        warn "Certificate copy job did not complete successfully"
        kubectl logs job/copy-wildcard-cert -n headscale || true
    }
fi

# Strict post-check: verify TLS secret exists; if missing, print actionable fix and exit with error
if ! kubectl get secret headscale-wildcard-tls -n headscale >/dev/null 2>&1; then
    echo ""
    warn "headscale-wildcard-tls not found in headscale namespace"
    echo "Attempting one-time fallback copy..."
    # Try dynamic source derived from DOMAIN, then fallback names
    SOURCE_SECRET=""
    for name in "${DOMAIN//./-}-wildcard-tls" "wildcard-tls"; do
        if kubectl get secret "$name" -n june-services >/dev/null 2>&1; then
            SOURCE_SECRET="$name"; break
        fi
    done
    if [ -n "$SOURCE_SECRET" ]; then
        kubectl get secret "$SOURCE_SECRET" -n june-services -o yaml | \
          sed 's/namespace: june-services/namespace: headscale/' | \
          sed "s/name: $SOURCE_SECRET/name: headscale-wildcard-tls/" | \
          kubectl apply -f - || true
    fi
fi

if ! kubectl get secret headscale-wildcard-tls -n headscale >/dev/null 2>&1; then
    echo ""
    error "TLS secret still missing. Run this command and re-check:\n\n  kubectl get secret ${DOMAIN//./-}-wildcard-tls -n june-services -o yaml | \\ \n    sed 's/namespace: june-services/namespace: headscale/' | \\ \n    sed 's/name: ${DOMAIN//./-}-wildcard-tls/name: headscale-wildcard-tls/' | \\ \n    kubectl apply -f -\n"
fi

log "Verifying Headscale deployment..."
HEADSCALE_POD=$(kubectl get pods -n headscale -l app=headscale -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$HEADSCALE_POD" ]; then
    log "Headscale pod: $HEADSCALE_POD"
    if kubectl exec -n headscale "$HEADSCALE_POD" -- headscale --version &>/dev/null; then
        success "Headscale binary is working correctly"
    else
        warn "Headscale binary check failed, but container is running"
    fi
else
    error "No Headscale pod found"
fi

echo ""
log "=== Headscale Deployment Status ==="
kubectl get all -n headscale

echo "\n🔐 TLS Secret:"
kubectl get secret headscale-wildcard-tls -n headscale

echo "\n🌐 Ingress:"
kubectl get ingress -n headscale

echo "\n📊 Service:"
kubectl get svc -n headscale

echo ""
success "Headscale VPN Control Plane deployment completed!"

echo "\n=== Access Information ==="
echo "  Headscale URL: https://headscale.$DOMAIN"
echo "  Tailscale Domain: tail.$DOMAIN"
echo "  Network Range: 100.64.0.0/10"
