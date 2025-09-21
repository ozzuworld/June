#!/bin/bash
# quick-terraform-fix.sh
# Quick fix for deletion protection without cluster deletion

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"

log "🔧 Quick fix: Disable deletion protection and continue with existing cluster"

cd infra/gke

# Step 1: Disable deletion protection on existing cluster
log "Disabling deletion protection..."
gcloud container clusters update "$CLUSTER_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --no-enable-deletion-protection

success "Deletion protection disabled"

# Step 2: Add deletion_protection = false to Terraform config
log "Updating Terraform config to disable deletion protection..."

# Add deletion_protection = false to the cluster resource
sed -i '/resource "google_container_cluster" "cluster" {/,/^}/ {
    /enable_autopilot = true/a\
\
  # Disable deletion protection\
  deletion_protection = false
}' main.tf

success "Updated main.tf with deletion_protection = false"

# Step 3: Import the existing cluster into Terraform state
log "Importing existing cluster into Terraform state..."
terraform import 'google_container_cluster.cluster' "projects/$PROJECT_ID/locations/$REGION/clusters/$CLUSTER_NAME" || true

# Step 4: Run terraform plan to see what needs to be done
log "Running terraform plan..."
terraform plan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="cluster_name=$CLUSTER_NAME"

cd ../..

success "🎉 Quick fix applied!"
log ""
log "📋 What was fixed:"
log "  ✅ Disabled deletion protection on existing cluster"
log "  ✅ Updated Terraform config"
log "  ✅ Imported cluster into Terraform state"
log ""
log "🚀 Now you can:"
log "  1. Continue with deployment: ./deploy-oracle-enterprise.sh"
log "  2. Or run: terraform apply (if plan looks good)"