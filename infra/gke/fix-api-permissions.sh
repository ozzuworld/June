#!/bin/bash
# fix-api-permissions.sh - Fix API and permission issues

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
error() { echo -e "${RED}❌ $1${NC}"; }

PROJECT_ID="main-buffer-469817-v7"

log "🔧 Fixing API permissions and enabling required services"

# Step 1: Check current authentication and permissions
log "Step 1: Checking authentication and permissions..."

CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
log "Current account: $CURRENT_ACCOUNT"

# Step 2: Check if billing is enabled
log "Step 2: Checking billing status..."
BILLING_ENABLED=$(gcloud beta billing projects describe $PROJECT_ID --format="value(billingEnabled)" 2>/dev/null || echo "unknown")

if [[ "$BILLING_ENABLED" != "True" ]]; then
    warning "Billing may not be enabled on this project"
    log "To enable billing, visit: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
    
    read -p "Continue anyway? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Billing must be enabled to use paid services like SQL and Redis"
    fi
fi

# Step 3: Enable APIs manually using gcloud (this often works when Terraform fails)
log "Step 3: Enabling APIs using gcloud CLI..."

REQUIRED_APIS=(
    "container.googleapis.com"
    "compute.googleapis.com"
    "sql.googleapis.com" 
    "redis.googleapis.com"
    "secretmanager.googleapis.com"
    "storage.googleapis.com"
)

for API in "${REQUIRED_APIS[@]}"; do
    log "Enabling $API..."
    if gcloud services enable "$API" --project="$PROJECT_ID"; then
        success "$API enabled successfully"
    else
        error "Failed to enable $API - check your permissions"
    fi
done

# Step 4: Wait for APIs to propagate
log "Step 4: Waiting for APIs to propagate..."
sleep 30

# Step 5: Verify APIs are enabled
log "Step 5: Verifying enabled APIs..."
ENABLED_APIS=$(gcloud services list --enabled --format="value(config.name)" --project="$PROJECT_ID")

for API in "${REQUIRED_APIS[@]}"; do
    if echo "$ENABLED_APIS" | grep -q "$API"; then
        success "$API is enabled"
    else
        warning "$API may not be fully enabled yet"
    fi
done

# Step 6: Check IAM permissions
log "Step 6: Checking IAM permissions..."
ROLES=$(gcloud projects get-iam-policy $PROJECT_ID --flatten="bindings[].members" --format="table(bindings.role)" --filter="bindings.members:$CURRENT_ACCOUNT" | tail -n +2)

log "Your current roles:"
echo "$ROLES"

REQUIRED_ROLES=("roles/editor" "roles/owner" "roles/container.admin")
HAS_REQUIRED_ROLE=false

for ROLE in "${REQUIRED_ROLES[@]}"; do
    if echo "$ROLES" | grep -q "$ROLE"; then
        success "You have $ROLE"
        HAS_REQUIRED_ROLE=true
        break
    fi
done

if [[ "$HAS_REQUIRED_ROLE" != "true" ]]; then
    warning "You may not have sufficient permissions. Required: Editor, Owner, or Container Admin"
    log "Contact your GCP admin to grant you 'Editor' role on project $PROJECT_ID"
fi

success "API permissions check complete!"
log ""
log "🔧 Next steps:"
log "1. Wait 2-3 minutes for API changes to propagate"
log "2. Re-run terraform apply"
log "3. If still failing, try the minimal deployment without Redis/SQL"