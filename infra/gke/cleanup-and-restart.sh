#!/bin/bash
# cleanup-and-restart.sh - Clean up failed deployment and restart fresh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"

log "🧹 Cleaning up failed deployment resources"
log "📋 Project: $PROJECT_ID | Region: $REGION | Cluster: $CLUSTER_NAME"

# Ensure we're in the right directory
if [[ ! -f "main.tf" ]]; then
    error "Please run this script from the infra/gke directory"
fi

# Step 1: Clean up Terraform state
log "Step 1: Cleaning up Terraform state"

if [[ -f "terraform.tfstate" ]]; then
    cp terraform.tfstate "terraform.tfstate.backup.$(date +%s)"
    success "Backed up Terraform state"
fi

if [[ -f "tfplan" ]]; then
    rm -f tfplan
    success "Removed old plan file"
fi

# Step 2: Disable deletion protection on existing cluster (if exists)
log "Step 2: Checking for existing cluster with deletion protection"

if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    warning "Found existing cluster with deletion protection. Disabling protection..."
    
    # Try to disable deletion protection
    gcloud container clusters update "$CLUSTER_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --no-enable-deletion-protection \
        --quiet || warning "Could not disable deletion protection automatically"
    
    success "Deletion protection disabled (if it was enabled)"
else
    log "No existing cluster found (this is normal for fresh deployments)"
fi

# Step 3: Clean up existing resources manually
log "Step 3: Cleaning up existing GCP resources"

# Delete existing cluster if it exists
if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    warning "Deleting existing cluster: $CLUSTER_NAME"
    gcloud container clusters delete "$CLUSTER_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --quiet
    success "Cluster deleted"
    
    # Wait for cluster deletion to complete
    log "Waiting for cluster deletion to complete..."
    sleep 30
fi

# Delete existing VPC if it exists
VPC_NAME="${CLUSTER_NAME}-vpc"
if gcloud compute networks describe "$VPC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    warning "Deleting existing VPC: $VPC_NAME"
    
    # First, delete any subnets
    SUBNETS=$(gcloud compute networks subnets list --network="$VPC_NAME" --format="value(name,region)" --project="$PROJECT_ID" 2>/dev/null || echo "")
    
    if [[ -n "$SUBNETS" ]]; then
        while IFS=$'\t' read -r subnet_name subnet_region; do
            if [[ -n "$subnet_name" && -n "$subnet_region" ]]; then
                log "Deleting subnet: $subnet_name in $subnet_region"
                gcloud compute networks subnets delete "$subnet_name" \
                    --region="$subnet_region" \
                    --project="$PROJECT_ID" \
                    --quiet || warning "Could not delete subnet $subnet_name"
            fi
        done <<< "$SUBNETS"
    fi
    
    # Delete the VPC
    gcloud compute networks delete "$VPC_NAME" \
        --project="$PROJECT_ID" \
        --quiet || warning "Could not delete VPC (may have dependencies)"
    
    success "VPC cleanup completed"
fi

# Delete existing static IP if it exists
STATIC_IP_NAME="june-services-ip"
if gcloud compute addresses describe "$STATIC_IP_NAME" --global --project="$PROJECT_ID" >/dev/null 2>&1; then
    warning "Deleting existing static IP: $STATIC_IP_NAME"
    gcloud compute addresses delete "$STATIC_IP_NAME" \
        --global \
        --project="$PROJECT_ID" \
        --quiet || warning "Could not delete static IP"
    success "Static IP deleted"
fi

# Step 4: Clean up service accounts
log "Step 4: Cleaning up service accounts"

SERVICE_ACCOUNTS=(
    "harbor-gke"
    "june-orchestrator-gke"
    "june-stt-gke"
    "june-tts-gke"
    "june-idp-gke"
)

for sa in "${SERVICE_ACCOUNTS[@]}"; do
    if gcloud iam service-accounts describe "${sa}@${PROJECT_ID}.iam.gserviceaccount.com" --project="$PROJECT_ID" >/dev/null 2>&1; then
        warning "Deleting service account: $sa"
        gcloud iam service-accounts delete "${sa}@${PROJECT_ID}.iam.gserviceaccount.com" \
            --project="$PROJECT_ID" \
            --quiet || warning "Could not delete service account $sa"
    fi
done

success "Service accounts cleaned up"

# Step 5: Reset Terraform state
log "Step 5: Resetting Terraform state"

# Remove state files to start fresh
rm -f terraform.tfstate*
rm -f .terraform.tfstate.lock.info

# Reinitialize Terraform
terraform init -upgrade
success "Terraform reinitialized"

# Step 6: Wait for resource cleanup to propagate
log "Step 6: Waiting for resource cleanup to propagate..."
sleep 30

# Step 7: Create updated terraform.tfvars
log "Step 7: Creating updated terraform.tfvars"

cat > terraform.tfvars << EOF
project_id = "$PROJECT_ID"
region = "$REGION"
cluster_name = "$CLUSTER_NAME"
EOF

success "Updated terraform.tfvars created"

# Step 8: Test Terraform plan
log "Step 8: Testing Terraform plan"

if terraform plan -out=tfplan; then
    success "✅ Terraform plan successful! Resources are clean."
    log ""
    log "🚀 Ready to deploy! Run the following commands:"
    log "   terraform apply tfplan"
    log "   # Or use the automated deployment script from the project root"
    log ""
    log "📋 Next steps after successful apply:"
    log "   1. Build and push container images"
    log "   2. Deploy Kubernetes manifests"
    log "   3. Configure DNS"
else
    error "Terraform plan still failing. Check the errors above."
fi

# Step 9: Summary
log "🎯 Cleanup Summary"
echo ""
echo "✅ Cleaned up:"
echo "  - Existing cluster (if any)"
echo "  - VPC network and subnets"
echo "  - Static IP addresses"
echo "  - Service accounts"
echo "  - Terraform state files"
echo ""
echo "🔄 What's next:"
echo "  1. Review the Terraform plan above"
echo "  2. Run: terraform apply tfplan"
echo "  3. Proceed with container deployment"
echo ""
echo "⚠️  If you still get errors, check:"
echo "  - GCP project permissions"
echo "  - API enablement status"
echo "  - Resource quotas"

success "Cleanup completed! You can now retry the deployme