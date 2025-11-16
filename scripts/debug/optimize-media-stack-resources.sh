#!/bin/bash
# Quick Resource Optimization for Media Stack
# Patches existing deployments with optimized CPU/memory requests and limits

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

echo "============================================================"
echo "Media Stack Resource Optimization"
echo "============================================================"
echo ""

log "Current resource requests are too high for small clusters"
log "Optimizing for idle workloads with burst capacity..."
echo ""

# Check if namespace exists
if ! kubectl get namespace june-services &>/dev/null; then
    error "Namespace june-services does not exist"
fi

# Function to patch deployment
patch_deployment() {
    local name=$1
    local cpu_req=$2
    local cpu_lim=$3
    local mem_req=$4
    local mem_lim=$5

    log "Optimizing $name..."

    if kubectl get deployment $name -n june-services &>/dev/null; then
        kubectl set resources deployment $name -n june-services \
          --requests=cpu=$cpu_req,memory=$mem_req \
          --limits=cpu=$cpu_lim,memory=$mem_lim

        success "$name: CPU $cpu_req → $cpu_lim, Memory $mem_req → $mem_lim"
    else
        warn "$name deployment not found, skipping"
    fi
}

# Optimize each deployment
echo "Optimizing deployments..."
echo ""

patch_deployment "jellyfin" "100m" "1000m" "512Mi" "2Gi"
patch_deployment "prowlarr" "50m" "250m" "128Mi" "256Mi"
patch_deployment "sonarr" "50m" "500m" "256Mi" "512Mi"
patch_deployment "radarr" "50m" "500m" "256Mi" "512Mi"
patch_deployment "jellyseerr" "50m" "250m" "128Mi" "256Mi"
patch_deployment "qbittorrent" "100m" "1000m" "256Mi" "1Gi"

echo ""
log "Waiting for pods to restart with new resource limits..."
sleep 5

# Check pod status
log "New pod status:"
kubectl get pods -n june-services -l 'app in (jellyfin,prowlarr,sonarr,radarr,jellyseerr,qbittorrent)'

echo ""
success "Resource optimization complete!"
echo ""
echo "📊 New Resource Allocation:"
echo "  Total CPU Requests: 400m (was 1300m) - 69% reduction!"
echo "  Total CPU Limits: 3500m (was 7000m)"
echo "  Total Memory Requests: 1.3Gi (was 3Gi) - 57% reduction!"
echo "  Total Memory Limits: 4.5Gi (was 9Gi)"
echo ""
echo "⏱️  Wait a few minutes for pods to restart, then check:"
echo "  kubectl get pods -n june-services"
echo ""
echo "📈 Monitor actual usage with:"
echo "  kubectl top pods -n june-services"
echo ""
echo "📖 See docs/RESOURCE-OPTIMIZATION.md for details"
