#!/bin/bash
# cleanup-old-tts.sh - Remove old TTS microservice and update configs

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

log "🧹 Starting TTS cleanup..."

# Step 1: Remove old TTS service directory
if [[ -d "June/services/june-tts" ]]; then
    warning "Removing June/services/june-tts/"
    rm -rf June/services/june-tts/
    success "Old TTS service removed"
else
    log "TTS service directory already removed"
fi

# Step 2: Update GitHub Actions workflow
if [[ -f ".github/workflows/deploy-gke.yml" ]]; then
    log "Updating GitHub Actions workflow..."
    
    # Remove TTS from build matrix
    sed -i 's/june-orchestrator, june-stt, june-tts, june-idp/june-orchestrator, june-stt, june-idp/' .github/workflows/deploy-gke.yml
    
    # Remove TTS context mapping
    sed -i '/june-tts:/d' .github/workflows/deploy-gke.yml
    sed -i '/June\/services\/june-tts/d' .github/workflows/deploy-gke.yml
    
    success "GitHub Actions updated"
fi

# Step 3: Update ingress to remove TTS endpoints
log "Updating ingress configuration..."

# Update ingress.yaml to remove TTS
if [[ -f "k8s/june-services/ingress.yaml" ]]; then
    # Create backup
    cp k8s/june-services/ingress.yaml k8s/june-services/ingress.yaml.backup
    
    # Remove TTS rules from ingress
    sed -i '/june-tts\.allsafe\.world/,+7d' k8s/june-services/ingress.yaml
    
    success "Ingress updated (backup created)"
fi

# Update managed certificates
if [[ -f "k8s/june-services/managedcert.yaml" ]]; then
    # Create backup
    cp k8s/june-services/managedcert.yaml k8s/june-services/managedcert.yaml.backup
    
    # Remove TTS domain
    sed -i '/june-tts\.allsafe\.world/d' k8s/june-services/managedcert.yaml
    
    success "Managed certificates updated (backup created)"
fi

# Step 4: Clean up unused Kubernetes manifests
log "Cleaning up unused Kubernetes manifests..."

cd k8s/june-services/

# Remove old/duplicate Keycloak manifests
UNUSED_MANIFESTS=(
    "keycloak-deployment-fixed.yaml"
    "keycloak-lightweight.yaml"
    "keycloak-production.yaml"
    "keycloak-fixed-startup.yaml"
    "june-orchestrator.yaml"  # Replaced by core-services-no-tts.yaml
)

for manifest in "${UNUSED_MANIFESTS[@]}"; do
    if [[ -f "$manifest" ]]; then
        warning "Removing unused manifest: $manifest"
        rm -f "$manifest"
    fi
done

# Remove old deployment scripts
UNUSED_SCRIPTS=(
    "fix-keycloak-jvm.sh"
    "fix-resource-constraints.sh"
    "patch-keycloak-startup.sh"
    "deploy-official-keycloak.sh"
    "deploy-production-keycloak.sh"
)

for script in "${UNUSED_SCRIPTS[@]}"; do
    if [[ -f "$script" ]]; then
        warning "Removing unused script: $script"
        rm -f "$script"
    fi
done

cd ../..

# Step 5: Clean up build artifacts
log "Cleaning up build artifacts..."

# Remove Python cache
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.log" -delete 2>/dev/null || true

# Remove Docker build artifacts  
rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true

success "Cleanup completed!"

echo ""
echo "📋 Summary of changes:"
echo "  ✅ Removed June/services/june-tts/ directory"
echo "  ✅ Updated GitHub Actions workflow"
echo "  ✅ Updated ingress configuration (backups created)"
echo "  ✅ Cleaned up unused Kubernetes manifests"
echo "  ✅ Removed old deployment scripts"
echo "  ✅ Cleaned up build artifacts"
echo ""
echo "📁 Files created:"
echo "  📄 external_tts_client.py (add to orchestrator)"
echo "  📄 core-services-no-tts.yaml (new deployment manifest)"
echo ""
echo "⚠️  Backups created for modified files:"
echo "  📄 k8s/june-services/ingress.yaml.backup"
echo "  📄 k8s/june-services/managedcert.yaml.backup"
echo ""
echo "🔄 Next steps:"
echo "  1. Set EXTERNAL_TTS_URL in secrets"
echo "  2. Deploy: kubectl apply -f k8s/june-services/core-services-no-tts.yaml"
echo "  3. Test integration"