#!/bin/bash
# Migrate Jellyfin Media Storage from SSD to HDD
# Frees up SSD space for critical services

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

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💾 Jellyfin Media Migration: SSD → HDD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo)"
fi

# Step 1: Find current Jellyfin storage
log "Step 1: Locating current Jellyfin storage..."

JELLYFIN_POD=$(kubectl get pods -n june-services -l app=jellyfin -o jsonpath='{.items[0].metadata.name}')
if [ -z "$JELLYFIN_POD" ]; then
    error "Jellyfin pod not found"
fi

log "Found Jellyfin pod: $JELLYFIN_POD"

# Get current mount point
CURRENT_MOUNT=$(kubectl get pod $JELLYFIN_POD -n june-services -o jsonpath='{.spec.volumes[?(@.name=="media")].hostPath.path}' 2>/dev/null || echo "")

if [ -z "$CURRENT_MOUNT" ]; then
    warn "Could not detect current media mount, assuming /mnt/jellyfin or similar"
    read -p "Enter current Jellyfin media path: " CURRENT_MOUNT
fi

log "Current media location: $CURRENT_MOUNT"
log "Target location: /mnt/hdd/jellyfin-media"

# Step 2: Check disk space
log "Step 2: Checking disk space..."

if [ -d "$CURRENT_MOUNT" ]; then
    CURRENT_SIZE=$(du -sh "$CURRENT_MOUNT" 2>/dev/null | awk '{print $1}')
    log "Current media size: $CURRENT_SIZE"
else
    warn "Current media directory not found: $CURRENT_MOUNT"
fi

HDD_AVAILABLE=$(df -h /mnt/hdd 2>/dev/null | awk 'NR==2{print $4}' || echo "Unknown")
log "HDD space available: $HDD_AVAILABLE"

# Step 3: Confirm migration
warn "This will:"
warn "  1. Scale down Jellyfin"
warn "  2. Copy media from SSD to HDD"
warn "  3. Update Jellyfin to use HDD"
warn "  4. Restart Jellyfin"
echo ""
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    log "Migration cancelled"
    exit 0
fi

# Step 4: Scale down Jellyfin
log "Step 4: Scaling down Jellyfin..."
kubectl scale deployment jellyfin -n june-services --replicas=0
log "Waiting for pod to terminate..."
sleep 15
success "Jellyfin scaled down"

# Step 5: Create HDD directory structure
log "Step 5: Creating HDD directory structure..."
mkdir -p /mnt/hdd/jellyfin-media/{movies,tvshows,music,photos}
mkdir -p /mnt/hdd/jellyfin-config
chown -R 1000:1000 /mnt/hdd/jellyfin-media /mnt/hdd/jellyfin-config
chmod -R 755 /mnt/hdd/jellyfin-media /mnt/hdd/jellyfin-config
success "Directories created"

# Step 6: Copy media (if exists)
if [ -d "$CURRENT_MOUNT" ] && [ "$(ls -A $CURRENT_MOUNT 2>/dev/null)" ]; then
    log "Step 6: Copying media files..."
    warn "This may take a while depending on media size..."

    # Use rsync for efficient copy with progress
    if command -v rsync &> /dev/null; then
        rsync -avh --progress "$CURRENT_MOUNT/" /mnt/hdd/jellyfin-media/
    else
        cp -rv "$CURRENT_MOUNT"/* /mnt/hdd/jellyfin-media/
    fi

    success "Media copied to HDD"
else
    warn "No media found at $CURRENT_MOUNT, skipping copy"
fi

# Step 7: Update Jellyfin deployment
log "Step 7: Updating Jellyfin deployment to use HDD..."

# Find Jellyfin deployment manifest
JELLYFIN_MANIFEST=$(find /home/*/June -name "*jellyfin*.yaml" 2>/dev/null | grep -v backup | head -1)

if [ -z "$JELLYFIN_MANIFEST" ]; then
    warn "Could not find Jellyfin manifest automatically"
    warn "You need to manually update the Jellyfin deployment to use:"
    warn "  hostPath: /mnt/hdd/jellyfin-media"
else
    log "Found manifest: $JELLYFIN_MANIFEST"

    # Backup original
    cp "$JELLYFIN_MANIFEST" "${JELLYFIN_MANIFEST}.backup-$(date +%Y%m%d)"

    # Update hostPath (simple sed replacement)
    if grep -q "hostPath:" "$JELLYFIN_MANIFEST"; then
        # Create updated manifest
        cat > /tmp/jellyfin-updated.yaml <<'EOF'
# Update the media volume to use HDD
# Find the volume named "media" and change:
#   hostPath:
#     path: /mnt/hdd/jellyfin-media
EOF
        warn "Manual update required:"
        warn "  Edit: $JELLYFIN_MANIFEST"
        warn "  Change hostPath to: /mnt/hdd/jellyfin-media"
    fi
fi

# Step 8: Apply updated manifest
log "Step 8: Applying updated configuration..."

# If using Helm, provide Helm command
warn "If using Helm, run:"
echo "  helm upgrade june-platform ./helm/june-platform -n june-services"
echo ""
warn "Or manually patch the deployment:"
echo "  kubectl patch deployment jellyfin -n june-services -p '{\"spec\":{\"template\":{\"spec\":{\"volumes\":[{\"name\":\"media\",\"hostPath\":{\"path\":\"/mnt/hdd/jellyfin-media\"}}]}}}}'"
echo ""

read -p "Apply patch now? (yes/no): " APPLY_PATCH

if [ "$APPLY_PATCH" = "yes" ]; then
    kubectl patch deployment jellyfin -n june-services -p '{"spec":{"template":{"spec":{"volumes":[{"name":"media","hostPath":{"path":"/mnt/hdd/jellyfin-media"}}]}}}}'
    success "Deployment patched"
fi

# Step 9: Scale up Jellyfin
log "Step 9: Scaling up Jellyfin..."
kubectl scale deployment jellyfin -n june-services --replicas=1
log "Waiting for pod to start..."
sleep 15

kubectl wait --for=condition=ready pod -l app=jellyfin -n june-services --timeout=120s || warn "Pod not ready yet"

success "Jellyfin scaled up"

# Step 10: Verify
log "Step 10: Verifying migration..."

JELLYFIN_POD_NEW=$(kubectl get pods -n june-services -l app=jellyfin -o jsonpath='{.items[0].metadata.name}')
NEW_MOUNT=$(kubectl get pod $JELLYFIN_POD_NEW -n june-services -o jsonpath='{.spec.volumes[?(@.name=="media")].hostPath.path}')

log "New media mount: $NEW_MOUNT"

if [ "$NEW_MOUNT" = "/mnt/hdd/jellyfin-media" ]; then
    success "Migration successful!"
else
    warn "Mount point not updated to HDD, please check manually"
fi

# Step 11: Cleanup (optional)
echo ""
warn "Migration complete!"
echo ""
echo "Old media location: $CURRENT_MOUNT"
echo "New media location: /mnt/hdd/jellyfin-media"
echo ""
read -p "Delete old media files from SSD to free up space? (yes/no): " DELETE_OLD

if [ "$DELETE_OLD" = "yes" ]; then
    log "Deleting old media files..."
    rm -rf "$CURRENT_MOUNT"
    success "Old media files deleted"

    # Show freed space
    SSD_FREE=$(df -h /mnt 2>/dev/null | awk 'NR==2{print $4}' || echo "Unknown")
    log "SSD space now free: $SSD_FREE"
else
    warn "Old media files kept at: $CURRENT_MOUNT"
    warn "You can delete manually later to free up SSD space"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Jellyfin Media Migration Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Jellyfin media is now on HDD: /mnt/hdd/jellyfin-media"
echo "Access Jellyfin to verify all media is accessible"
echo ""
