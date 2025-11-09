#!/bin/bash
# June Platform - Jellyfin Installation Phase
# Installs Jellyfin media server using official Helm chart

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

ROOT_DIR="$1"

# Load configuration if not already loaded
if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    
    CONFIG_FILE="${ROOT_DIR}/config.env"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found: $CONFIG_FILE"
    fi
    
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

# Validate DOMAIN is set
if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set. Please check your config.env file."
fi

log "Installing Jellyfin Media Server for domain: $DOMAIN"

# Ensure june-services namespace exists
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Add Jellyfin Helm repository
log "Adding Jellyfin Helm repository..."
helm repo add jellyfin https://jellyfin.github.io/jellyfin-helm
helm repo update

# Create persistent volume for Jellyfin config
log "Creating Jellyfin configuration storage..."
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
  storageClassName: ""
  hostPath:
    path: /mnt/jellyfin/config
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
  storageClassName: ""
  hostPath:
    path: /mnt/jellyfin/media
    type: DirectoryOrCreate
EOF

# Create values file for Jellyfin
log "Creating Jellyfin Helm values..."
cat > /tmp/jellyfin-values.yaml <<EOF
persistence:
  config:
    enabled: true
    storageClass: ""
    size: 5Gi
  media:
    enabled: true
    storageClass: ""
    size: 500Gi

service:
  type: ClusterIP
  port: 8096

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
  hosts:
    - host: jellyfin.${DOMAIN}
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: jellyfin-tls
      hosts:
        - jellyfin.${DOMAIN}

resources:
  requests:
    memory: 1Gi
    cpu: 500m
  limits:
    memory: 4Gi
    cpu: 2000m
EOF

# Show the generated values for verification
log "Generated Jellyfin configuration for: jellyfin.${DOMAIN}"

# Install Jellyfin via Helm
log "Installing Jellyfin with Helm..."
helm upgrade --install jellyfin jellyfin/jellyfin \
  --namespace june-services \
  --values /tmp/jellyfin-values.yaml \
  --wait \
  --timeout 10m

# Wait for Jellyfin to be ready
log "Waiting for Jellyfin to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=jellyfin \
  -n june-services \
  --timeout=300s || warn "Jellyfin pod not ready yet"

# Get Jellyfin status
log "Jellyfin deployment status:"
kubectl get pods -n june-services -l app.kubernetes.io/name=jellyfin

success "Jellyfin installed successfully!"
echo ""
echo "📺 Jellyfin Access:"
echo "  URL: https://jellyfin.${DOMAIN}"
echo "  First-time setup: Navigate to URL and complete setup wizard"
echo ""
echo "📁 Storage Locations:"
echo "  Config: /mnt/jellyfin/config"
echo "  Media: /mnt/jellyfin/media"
echo ""
echo "🔐 Note: Update DNS to point jellyfin.${DOMAIN} to your server IP"
