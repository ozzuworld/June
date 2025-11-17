#!/bin/bash
# Media Stack - Namespace Setup
# Creates media-stack namespace and sets up certificate synchronization

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Please run from June project directory"
fi

if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

log "Setting up media-stack namespace..."

# Verify june-services namespace exists (we need it for cert copying)
if ! kubectl get namespace june-services &>/dev/null; then
    error "june-services namespace not found. Please install core services first."
fi

# Create media-stack namespace and RBAC for certificate copying
log "Creating media-stack namespace..."
kubectl apply -f "${ROOT_DIR}/k8s/media-stack/00-namespace.yaml"

# Wait for namespace to be active (with manual fallback)
log "Waiting for namespace to be active..."
if ! kubectl wait --for=condition=Active --timeout=60s namespace/media-stack 2>/dev/null; then
    # Fallback: check if namespace exists manually
    if kubectl get namespace media-stack &>/dev/null; then
        log "Namespace exists, proceeding despite wait timeout..."
        # Give it a few more seconds
        sleep 5
    else
        error "Failed to create media-stack namespace"
    fi
fi

success "media-stack namespace created"

# Apply certificate sync CronJob
log "Setting up certificate synchronization..."
kubectl apply -f "${ROOT_DIR}/k8s/media-stack/01-cert-sync-cronjob.yaml"

success "Certificate sync CronJob created (runs every 5 minutes)"

# Perform initial certificate sync manually
log "Performing initial certificate sync..."

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"

if kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services &>/dev/null; then
    log "Found wildcard certificate: $WILDCARD_SECRET_NAME"

    # Copy certificate to media-stack namespace
    kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services -o yaml | \
        sed "s/namespace: june-services/namespace: media-stack/" | \
        kubectl apply -f -

    success "Certificate copied to media-stack namespace"
else
    warn "Wildcard certificate not found in june-services namespace"
    warn "Certificate will be synced automatically once it's available"
fi

# Verify media-stack namespace
log "Verifying media-stack namespace setup..."
verify_namespace "media-stack"

log "Namespace status:"
kubectl get namespace media-stack

if kubectl get secret "$WILDCARD_SECRET_NAME" -n media-stack &>/dev/null; then
    success "Certificate verified in media-stack namespace"
else
    warn "Certificate not yet available in media-stack namespace"
fi

success "Media stack namespace setup completed"
echo ""
echo "📦 Namespace: media-stack"
echo "🔐 Certificate sync: Active (every 5 minutes)"
echo "📜 Certificate: $WILDCARD_SECRET_NAME"
echo ""
