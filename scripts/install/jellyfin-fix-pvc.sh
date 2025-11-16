#!/bin/bash
# Fix Jellyfin PVC scheduling issue by creating the missing media PV
# This script can be run on existing deployments without redeploying Jellyfin

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

log "Fixing Jellyfin PVC scheduling issue..."

# Ensure media directory exists
log "Ensuring media directory structure exists..."
mkdir -p /mnt/jellyfin/media/movies
mkdir -p /mnt/jellyfin/media/tv
mkdir -p /mnt/jellyfin/media/downloads/complete
mkdir -p /mnt/jellyfin/media/downloads/incomplete

# Set proper ownership (UID 1000 matches Jellyfin container user)
chown -R 1000:1000 /mnt/jellyfin/media
chmod -R 755 /mnt/jellyfin/media

# Check if jellyfin-media-pv already exists
if kubectl get pv jellyfin-media-pv &>/dev/null; then
    warn "PersistentVolume jellyfin-media-pv already exists, skipping creation"
else
    # Create persistent volume for Jellyfin media
    log "Creating Jellyfin media PersistentVolume..."
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: jellyfin-media-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/jellyfin/media
    type: DirectoryOrCreate
EOF
    success "Created jellyfin-media-pv"
fi

# Wait for PVC to bind
log "Waiting for PVC to bind..."
sleep 2

# Check PV and PVC status
log "PersistentVolume status:"
kubectl get pv | grep jellyfin || warn "No Jellyfin PVs found"

log "PersistentVolumeClaim status:"
kubectl get pvc -n june-services | grep jellyfin || warn "No Jellyfin PVCs found"

# Check if pod is now scheduled
log "Checking pod status..."
POD_STATUS=$(kubectl get pods -n june-services -l app.kubernetes.io/name=jellyfin -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")

if [ "$POD_STATUS" = "Running" ]; then
    success "Jellyfin pod is now running!"
elif [ "$POD_STATUS" = "Pending" ]; then
    warn "Jellyfin pod is still pending. Check with: kubectl describe pod -n june-services -l app.kubernetes.io/name=jellyfin"
    log "The scheduler may need a moment to detect the new PV and bind the PVC"
elif [ "$POD_STATUS" = "NotFound" ]; then
    warn "No Jellyfin pod found"
else
    warn "Jellyfin pod status: $POD_STATUS"
fi

success "Fix applied!"
echo ""
echo "📊 Verification commands:"
echo "  kubectl get pv | grep jellyfin"
echo "  kubectl get pvc -n june-services | grep jellyfin"
echo "  kubectl get pods -n june-services -l app.kubernetes.io/name=jellyfin"
echo "  kubectl describe pod -n june-services -l app.kubernetes.io/name=jellyfin"
echo ""
echo "💡 If the pod is still pending, the PVC may need to be recreated:"
echo "  kubectl delete pod -n june-services -l app.kubernetes.io/name=jellyfin"
echo "  (Kubernetes will automatically recreate the pod)"
