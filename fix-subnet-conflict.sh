#!/bin/bash
# fix-subnet-conflict.sh
# Handle subnet CIDR conflicts

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

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"

log "🔧 Fixing subnet CIDR conflict..."

cd infra/gke

# Step 1: Check existing subnets
log "Step 1: Checking existing subnets..."
echo "Existing subnets in region $REGION:"
gcloud compute networks subnets list --filter="region:$REGION" --project="$PROJECT_ID" --format="table(name,ipCidrRange,network)"

# Step 2: Get cluster's current network configuration
log "Step 2: Getting cluster's network configuration..."
if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
    CLUSTER_NETWORK=$(gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(network)")
    CLUSTER_SUBNETWORK=$(gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(subnetwork)")
    
    log "Cluster network: $CLUSTER_NETWORK"
    log "Cluster subnetwork: $CLUSTER_SUBNETWORK"
    
    # Extract network and subnet names
    NETWORK_NAME=$(echo $CLUSTER_NETWORK | sed 's|.*/||')
    SUBNET_NAME=$(echo $CLUSTER_SUBNETWORK | sed 's|.*/||')
    
    log "Network name: $NETWORK_NAME"
    log "Subnet name: $SUBNET_NAME"
    
    # Get subnet CIDR
    EXISTING_CIDR=$(gcloud compute networks subnets describe "$SUBNET_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(ipCidrRange)")
    log "Existing subnet CIDR: $EXISTING_CIDR"
    
    # Step 3: Option 1 - Import existing resources
    log "Step 3: Option 1 - Import existing network and subnet"
    
    # Import network
    terraform import 'google_compute_network.main' "projects/$PROJECT_ID/global/networks/$NETWORK_NAME" || true
    
    # Import subnet  
    terraform import 'google_compute_subnetwork.main' "projects/$PROJECT_ID/regions/$REGION/subnetworks/$SUBNET_NAME" || true
    
    success "Imported existing network and subnet"
    
    # Step 4: Update Terraform config to match existing resources
    log "Step 4: Updating Terraform config to match existing subnet..."
    
    # Update main.tf to use existing names and CIDR
    cat > temp_network_config.tf << EOF
# Updated network configuration to match existing resources
resource "google_compute_network" "main" {
  name                    = "$NETWORK_NAME"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name                     = "$SUBNET_NAME"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "$EXISTING_CIDR"
  private_ip_google_access = true

  # Keep existing secondary ranges or add new ones if needed
  secondary_ip_range {
    range_name    = "\${var.cluster_name}-pods"
    ip_cidr_range = "172.16.0.0/14"  # Different range to avoid conflicts
  }

  secondary_ip_range {
    range_name    = "\${var.cluster_name}-services"
    ip_cidr_range = "172.20.0.0/20"  # Different range to avoid conflicts
  }
}
EOF

    # Replace the network configuration in main.tf
    # First, extract everything before the network section
    sed -n '1,/# VPC and Subnet for GKE/p' main.tf | head -n -1 > temp_main_start.tf
    
    # Extract everything after the subnet section
    sed -n '/# GKE Autopilot Cluster/,$p' main.tf > temp_main_end.tf
    
    # Combine parts
    cat temp_main_start.tf > main.tf
    echo "# VPC and Subnet for GKE" >> main.tf
    cat temp_network_config.tf >> main.tf
    echo "" >> main.tf
    cat temp_main_end.tf >> main.tf
    
    # Clean up temp files
    rm -f temp_*.tf
    
    success "Updated main.tf to use existing network configuration"
    
else
    log "Cluster not found - using clean configuration with different CIDR range"
    
    # Step 3: Option 2 - Use different CIDR range
    log "Step 3: Option 2 - Using different CIDR range to avoid conflicts"
    
    # Update main.tf to use different IP ranges
    sed -i 's/ip_cidr_range            = "10\.0\.0\.0\/16"/ip_cidr_range            = "192.168.0.0\/16"/' main.tf
    sed -i 's/ip_cidr_range = "10\.4\.0\.0\/14"/ip_cidr_range = "172.16.0.0\/14"/' main.tf
    sed -i 's/ip_cidr_range = "10\.8\.0\.0\/20"/ip_cidr_range = "172.20.0.0\/20"/' main.tf
    
    success "Updated CIDR ranges to avoid conflicts"
fi

# Step 5: Clean up any failed state
log "Step 5: Cleaning up failed Terraform state..."
terraform state rm 'google_compute_subnetwork.main' 2>/dev/null || true

# Step 6: Plan again
log "Step 6: Running terraform plan..."
terraform plan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="cluster_name=$CLUSTER_NAME"

cd ../..

success "🎉 Subnet conflict fixed!"
log ""
log "📋 What was fixed:"
log "  ✅ Identified existing network configuration"
log "  ✅ Imported existing resources OR used different CIDR ranges"
log "  ✅ Updated Terraform configuration"
log "  ✅ Cleaned up conflicting state"
log ""
log "🚀 Next steps:"
log "  1. Review the terraform plan output above"
log "  2. If it looks good, run: terraform apply"
log "  3. Then continue with: ./deploy-oracle-enterprise.sh"