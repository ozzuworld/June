#!/bin/bash
# Media Stack - Jellyfin Installation
# Installs Jellyfin media server in media-stack namespace

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

if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set. Please check your config.env file."
fi

NAMESPACE="media-stack"
log "Installing Jellyfin Media Server in $NAMESPACE namespace for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Using wildcard certificate: $WILDCARD_SECRET_NAME"

# Verify namespace exists
verify_namespace "$NAMESPACE"

# Create directory structure on host
log "Creating Jellyfin directory structure..."
mkdir -p /mnt/ssd/jellyfin-config
mkdir -p /mnt/hdd/jellyfin-media/movies
mkdir -p /mnt/hdd/jellyfin-media/tv
mkdir -p /mnt/hdd/jellyfin-media/downloads/complete
mkdir -p /mnt/hdd/jellyfin-media/downloads/incomplete

# Set proper ownership
chown -R 1000:1000 /mnt/ssd/jellyfin-config
chown -R 1000:1000 /mnt/hdd/jellyfin-media
chmod -R 755 /mnt/hdd/jellyfin-media

# Add Jellyfin Helm repository
log "Adding Jellyfin Helm repository..."
helm repo add jellyfin https://jellyfin.github.io/jellyfin-helm 2>/dev/null || true
helm repo update

# Create persistent volumes
log "Creating Jellyfin persistent volumes..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: jellyfin-config-pv
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/jellyfin-config
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: jellyfin-media-pv
spec:
  capacity:
    storage: 500Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "slow-hdd"
  hostPath:
    path: /mnt/hdd/jellyfin-media
    type: DirectoryOrCreate
EOF

# Create Helm values
log "Creating Jellyfin Helm values..."
cat > /tmp/jellyfin-values.yaml <<EOF
persistence:
  config:
    enabled: true
    storageClass: "fast-ssd"
    size: 5Gi
  media:
    enabled: true
    storageClass: "slow-hdd"
    size: 500Gi

podSecurityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000

service:
  type: ClusterIP
  port: 8096

ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
  hosts:
    - host: tv.${DOMAIN}
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: ${WILDCARD_SECRET_NAME}
      hosts:
        - tv.${DOMAIN}

resources:
  requests:
    memory: 512Mi
    cpu: 100m
  limits:
    memory: 2Gi
    cpu: 1000m
EOF

# Verify wildcard certificate exists
if kubectl get secret "$WILDCARD_SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    success "Wildcard certificate found: $WILDCARD_SECRET_NAME"
else
    warn "Wildcard certificate not found: $WILDCARD_SECRET_NAME"
    warn "Jellyfin will still deploy, but HTTPS may not work until certificate is synced"
fi

# Install Jellyfin via Helm
log "Installing Jellyfin with Helm..."
helm upgrade --install jellyfin jellyfin/jellyfin \
  --namespace "$NAMESPACE" \
  --values /tmp/jellyfin-values.yaml \
  --wait \
  --timeout 10m

# Wait for Jellyfin to be ready
log "Waiting for Jellyfin to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=jellyfin \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Jellyfin pod not ready yet"

# Get Jellyfin status
log "Jellyfin deployment status:"
kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=jellyfin

# Verify ingress
log "Jellyfin ingress status:"
kubectl get ingress -n "$NAMESPACE" | grep jellyfin || warn "No Jellyfin ingress found"

success "Jellyfin installed successfully in $NAMESPACE namespace!"
echo ""
echo "📺 Jellyfin Access:"
echo "  URL: https://tv.${DOMAIN}"
echo "  Namespace: $NAMESPACE"
echo ""
echo "📁 Storage Locations:"
echo "  Config: /mnt/ssd/jellyfin-config (SSD)"
echo "  Media: /mnt/hdd/jellyfin-media (HDD)"
echo ""
