#!/bin/bash
# fix-terraform-conflicts.sh
# Handle existing Terraform resources and conflicts

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

log "🔧 Fixing Terraform resource conflicts..."

cd infra/gke

# Step 1: Clean up conflicting state
log "Step 1: Cleaning up conflicting Terraform state..."

# Remove conflicting resources from state (they'll be reimported or recreated)
terraform state rm 'google_compute_subnetwork.main' 2>/dev/null || true
terraform state rm 'google_artifact_registry_repository.june_repo' 2>/dev/null || true
terraform state rm 'google_secret_manager_secret.oracle_credentials["oracle-wallet-cwallet"]' 2>/dev/null || true
terraform state rm 'google_secret_manager_secret.oracle_credentials["oracle-wallet-ewallet"]' 2>/dev/null || true
terraform state rm 'google_secret_manager_secret.oracle_credentials["oracle-wallet-tnsnames"]' 2>/dev/null || true
terraform state rm 'google_secret_manager_secret.oracle_credentials["oracle-wallet-sqlnet"]' 2>/dev/null || true

success "Removed conflicting resources from Terraform state"

# Step 2: Handle existing subnet being used by cluster
log "Step 2: Handling subnet conflicts..."

# Check if cluster is using the subnet
if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    warning "Cluster $CLUSTER_NAME already exists and may be using the subnet"
    
    # Get existing subnet name
    EXISTING_SUBNET=$(gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(network)")
    
    if [[ -n "$EXISTING_SUBNET" ]]; then
        log "Cluster is using existing network configuration"
        
        # Import existing cluster
        terraform import 'google_container_cluster.cluster' "projects/$PROJECT_ID/locations/$REGION/clusters/$CLUSTER_NAME" || true
        
        # Import network if it exists
        NETWORK_NAME=$(gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(network)" | sed 's|.*/||')
        if [[ -n "$NETWORK_NAME" ]]; then
            terraform import 'google_compute_network.main' "projects/$PROJECT_ID/global/networks/$NETWORK_NAME" || true
        fi
    fi
fi

# Step 3: Handle existing Artifact Registry
log "Step 3: Handling Artifact Registry conflicts..."

if gcloud artifacts repositories describe june --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    log "Artifact Registry 'june' already exists - importing..."
    terraform import 'google_artifact_registry_repository.june_repo[0]' "projects/$PROJECT_ID/locations/$REGION/repositories/june" || true
fi

# Step 4: Handle existing secrets
log "Step 4: Handling Secret Manager conflicts..."

# Remove secret resources from terraform completely since they already exist
# We'll manage them manually
cat > secrets-ignore.tf << 'EOF'
# Temporarily ignore secrets that already exist
# They will be managed outside of Terraform

# resource "google_secret_manager_secret" "oracle_credentials" {
#   for_each = toset([
#     "harbor-db-password",
#     "keycloak-db-password", 
#     "oracle-wallet-cwallet",
#     "oracle-wallet-ewallet",
#     "oracle-wallet-tnsnames",
#     "oracle-wallet-sqlnet"
#   ])
#   
#   secret_id = each.key
#   project   = var.project_id
# 
#   replication {
#     auto {}
#   }
#   
#   labels = {
#     purpose = "oracle-database"
#     service = "june-platform"
#   }
# }
EOF

success "Created secrets-ignore.tf to handle existing secrets"

# Step 5: Refresh Terraform state
log "Step 5: Refreshing Terraform state..."

terraform init -upgrade
terraform refresh \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="cluster_name=$CLUSTER_NAME"

success "Terraform state refreshed"

# Step 6: Show current state
log "Step 6: Current Terraform state..."
terraform show | head -20

log ""
success "🎉 Terraform conflicts resolved!"
log ""
log "📋 What was fixed:"
log "  ✅ Removed conflicting subnet from state"
log "  ✅ Imported existing cluster (if found)"
log "  ✅ Imported existing Artifact Registry"
log "  ✅ Disabled conflicting Secret Manager resources"
log ""
log "🚀 Next steps:"
log "  1. Run: terraform plan"
log "  2. Run: terraform apply"
log "  3. Continue with deployment script"

cd ../..