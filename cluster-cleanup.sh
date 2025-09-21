#!/bin/bash
# cluster-cleanup.sh
# Handle GKE cluster deletion protection and cleanup

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"

log "🗑️ Cleaning up GKE cluster with deletion protection..."

# Option 1: Disable deletion protection via gcloud (fastest)
log "Step 1: Disabling deletion protection via gcloud..."

if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    log "Cluster $CLUSTER_NAME exists, disabling deletion protection..."
    
    gcloud container clusters update "$CLUSTER_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --no-enable-deletion-protection
    
    success "Deletion protection disabled"
    
    # Option 2: Delete cluster directly via gcloud (faster than Terraform)
    read -p "Delete cluster $CLUSTER_NAME directly via gcloud? (y/N): " -r
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Deleting cluster via gcloud..."
        gcloud container clusters delete "$CLUSTER_NAME" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --quiet
        
        success "Cluster deleted successfully"
        
        # Clean up Terraform state
        cd infra/gke
        terraform state rm 'google_container_cluster.cluster' 2>/dev/null || true
        cd ../..
        
        success "Terraform state cleaned up"
    else
        log "Cluster kept - you can now run terraform destroy"
    fi
else
    warning "Cluster $CLUSTER_NAME not found - may already be deleted"
fi

# Option 3: Clean up remaining resources
log "Step 2: Cleaning up remaining resources..."

# Delete any remaining LoadBalancers
kubectl delete svc --all -n june-services 2>/dev/null || true

# Clean up namespaces
kubectl delete namespace june-services --ignore-not-found=true
kubectl delete namespace harbor --ignore-not-found=true

# Clean up global IP if it exists
gcloud compute addresses delete june-services-ip --global --project="$PROJECT_ID" --quiet 2>/dev/null || true

success "Resource cleanup completed"

log ""
success "🎉 Cleanup completed!"
log ""
log "📋 What was cleaned up:"
log "  ✅ Disabled cluster deletion protection"
log "  ✅ Deleted cluster (if you chose to)"
log "  ✅ Cleaned up Kubernetes resources"
log "  ✅ Removed global IP address"
log ""
log "🚀 Next steps:"
log "  1. Run fresh deployment: ./deploy-oracle-enterprise.sh"
log "  2. Or continue with Terraform: terraform plan && terraform apply"