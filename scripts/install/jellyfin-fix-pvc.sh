#!/bin/bash
# Fix Jellyfin PVC scheduling issue by migrating media storage from SSD to HDD
# This handles the case where jellyfin-media PVC was created with wrong storageClass

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

log "Fixing Jellyfin storage configuration..."
log "Config will stay on SSD (fast-ssd), Media will move to HDD (hostPath)"

# Ensure media directory exists on HDD
log "Ensuring media directory structure exists on HDD..."
mkdir -p /mnt/jellyfin/media/movies
mkdir -p /mnt/jellyfin/media/tv
mkdir -p /mnt/jellyfin/media/downloads/complete
mkdir -p /mnt/jellyfin/media/downloads/incomplete

# Set proper ownership (UID 1000 matches Jellyfin container user)
chown -R 1000:1000 /mnt/jellyfin/media
chmod -R 755 /mnt/jellyfin/media

# Check current PVC status
log "Current PVC configuration:"
kubectl get pvc -n june-services jellyfin-media -o jsonpath='{.spec.storageClassName}' 2>/dev/null && echo "" || true

CURRENT_STORAGE_CLASS=$(kubectl get pvc -n june-services jellyfin-media -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "")

if [ "$CURRENT_STORAGE_CLASS" = "fast-ssd" ]; then
    warn "jellyfin-media PVC is using fast-ssd storageClass (on SSD)"
    warn "Need to delete and recreate to use HDD hostPath storage"
    echo ""
    read -p "Delete jellyfin-media PVC and recreate on HDD? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        log "Fix cancelled"
        exit 0
    fi

    # Scale down Jellyfin
    log "Scaling down Jellyfin..."
    kubectl scale deployment jellyfin -n june-services --replicas=0
    sleep 3

    # Delete the PVC
    log "Deleting jellyfin-media PVC..."
    kubectl delete pvc jellyfin-media -n june-services --wait=true
fi

# Create or update the PV
log "Creating/updating jellyfin-media-pv on HDD..."
cat <<EOF | kubectl apply -f -
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

# Scale back up Jellyfin (will recreate PVC with correct storageClass)
log "Scaling Jellyfin back up..."
kubectl scale deployment jellyfin -n june-services --replicas=1

# Wait a moment for PVC to be created
sleep 5

# Check PV and PVC status
log "PersistentVolume status:"
kubectl get pv jellyfin-media-pv 2>/dev/null || warn "PV not found"

log "PersistentVolumeClaim status:"
kubectl get pvc -n june-services jellyfin-media 2>/dev/null || warn "PVC not found yet"

# Wait for pod
log "Waiting for Jellyfin pod to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=jellyfin \
  -n june-services \
  --timeout=180s || warn "Pod not ready yet"

success "Fix applied!"
echo ""
echo "📊 Current status:"
kubectl get pv | grep jellyfin
echo ""
kubectl get pvc -n june-services | grep jellyfin
echo ""
kubectl get pods -n june-services -l app.kubernetes.io/name=jellyfin
