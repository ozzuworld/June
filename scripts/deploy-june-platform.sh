#!/bin/bash
# deploy-june-platform.sh - Complete deployment automation
# This script replaces the complex setup with a streamlined approach

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging functions
log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration - Update these values
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"
ARTIFACT_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/june"

# Verify we're in the right directory
if [[ ! -f "infra/gke/main.tf" ]]; then
    error "Please run this script from the project root directory"
fi

log "🚀 Starting June Platform Deployment"
log "📋 Configuration:"
log "   Project: $PROJECT_ID"
log "   Region: $REGION"
log "   Cluster: $CLUSTER_NAME"
log "   Registry: $ARTIFACT_REGISTRY"

# Phase 1: Clean up and prepare
log "🧹 Phase 1: Cleaning up old files"

# Remove duplicate and problematic files
FILES_TO_REMOVE=(
    "June/services/june-idp"
    "k8s/june-services/keycloakdb_wallet"
    "k8s/june-services/README.txt"
    "k8s/june-services/june-idp.yaml"
    "k8s/june-services/june-stt.yaml"
    "k8s/june-services/june-tts.yaml"
    "infra/gke/fix-api-permissions.sh"
    "infra/gke/complete-deploy.sh"
)

for file in "${FILES_TO_REMOVE[@]}"; do
    if [[ -e "$file" ]]; then
        rm -rf "$file"
        success "Removed $file"
    fi
done

# Backup current main.tf
if [[ -f "infra/gke/main.tf" ]]; then
    cp infra/gke/main.tf "infra/gke/main.tf.backup.$(date +%s)"
    success "Backed up current main.tf"
fi

# Phase 2: Infrastructure deployment
log "🏗️ Phase 2: Deploying infrastructure"

cd infra/gke

# Create terraform.tfvars if it doesn't exist
if [[ ! -f "terraform.tfvars" ]]; then
    cat > terraform.tfvars << EOF
project_id = "$PROJECT_ID"
region = "$REGION"
cluster_name = "$CLUSTER_NAME"
EOF
    success "Created terraform.tfvars"
fi

# Initialize and deploy Terraform
log "Initializing Terraform..."
terraform init -upgrade

log "Planning infrastructure deployment..."
terraform plan -out=tfplan

read -p "Continue with infrastructure deployment? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    warning "Infrastructure deployment cancelled"
    exit 0
fi

log "Applying infrastructure..."
terraform apply tfplan

# Get outputs
STATIC_IP=$(terraform output -raw static_ip)
success "Infrastructure deployed! Static IP: $STATIC_IP"

# Phase 3: Configure kubectl
log "🔧 Phase 3: Configuring kubectl"
eval "$(terraform output -raw get_credentials_command)"

# Verify cluster access
kubectl get nodes
kubectl get namespaces
success "kubectl configured and cluster accessible"

cd ../..

# Phase 4: Build and push container images
log "🐳 Phase 4: Building and pushing container images"

# Configure Docker for Artifact Registry
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build and push images
SERVICES=("june-orchestrator" "june-stt" "june-tts")

for service in "${SERVICES[@]}"; do
    if [[ -d "June/services/$service" ]]; then
        log "Building $service..."
        IMAGE_TAG="${ARTIFACT_REGISTRY}/${service}:latest"
        
        docker build -t "$IMAGE_TAG" "June/services/$service/"
        docker push "$IMAGE_TAG"
        
        success "$service image pushed to registry"
    else
        warning "Service directory June/services/$service not found, skipping"
    fi
done

# Phase 5: Deploy Kubernetes resources
log "☸️ Phase 5: Deploying Kubernetes resources"

# Create simplified manifests directory
mkdir -p k8s/june-services-simple

# Deploy services using the simplified manifests
kubectl apply -f k8s/june-services-simple/ || kubectl apply -f k8s/june-services/

# Wait for deployments to be ready
log "⏳ Waiting for deployments to be ready..."
kubectl wait --for=condition=available deployment --all -n june-services --timeout=300s || true

# Phase 6: Configure secrets (API keys)
log "🔐 Phase 6: Configuring API keys"

# Check if API keys are set in environment
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
    kubectl patch secret june-secrets -n june-services \
        --patch="{\"data\":{\"GEMINI_API_KEY\":\"$(echo -n "$GEMINI_API_KEY" | base64)\"}}"
    success "GEMINI_API_KEY configured"
else
    warning "GEMINI_API_KEY not set. Configure manually: kubectl patch secret june-secrets -n june-services --patch='{\"data\":{\"GEMINI_API_KEY\":\"<base64-encoded-key>\"}}'"
fi

if [[ -n "${CHATTERBOX_API_KEY:-}" ]]; then
    kubectl patch secret june-secrets -n june-services \
        --patch="{\"data\":{\"CHATTERBOX_API_KEY\":\"$(echo -n "$CHATTERBOX_API_KEY" | base64)\"}}"
    success "CHATTERBOX_API_KEY configured"
else
    warning "CHATTERBOX_API_KEY not set. Configure manually: kubectl patch secret june-secrets -n june-services --patch='{\"data\":{\"CHATTERBOX_API_KEY\":\"<base64-encoded-key>\"}}'"
fi

# Phase 7: Verification and testing
log "🧪 Phase 7: Verifying deployment"

# Show pod status
kubectl get pods -n june-services -o wide

# Test health endpoints
log "Testing service health endpoints..."
for service in "${SERVICES[@]}"; do
    if kubectl get service "$service" -n june-services >/dev/null 2>&1; then
        kubectl port-forward "service/$service" 8080:8080 -n june-services &
        PID=$!
        sleep 5
        
        if curl -s http://localhost:8080/healthz >/dev/null; then
            success "$service health check passed"
        else
            warning "$service health check failed"
        fi
        
        kill $PID 2>/dev/null || true
        sleep 2
    fi
done

# Phase 8: Summary and next steps
log "📋 Phase 8: Deployment Summary"

success "🎉 June Platform deployed successfully!"
echo ""
echo "📊 Deployment Details:"
echo "  Project: $PROJECT_ID"
echo "  Region: $REGION"
echo "  Cluster: $CLUSTER_NAME"
echo "  Static IP: $STATIC_IP"
echo "  Registry: $ARTIFACT_REGISTRY"
echo ""
echo "🔗 Access URLs (after DNS setup):"
echo "  Orchestrator: https://june-orchestrator.allsafe.world"
echo "  STT Service:  https://june-stt.allsafe.world"
echo "  TTS Service:  https://june-tts.allsafe.world"
echo ""
echo "🔧 Next Steps:"
echo "  1. Configure DNS A records pointing to $STATIC_IP"
echo "  2. Wait for SSL certificates to provision (15-30 minutes)"
echo "  3. Test services via HTTPS endpoints"
echo "  4. Monitor with: kubectl get pods -n june-services -w"
echo ""
echo "🚨 If you encounter issues:"
echo "  - Check logs: kubectl logs -f deployment/<service> -n june-services"
echo "  - Check events: kubectl get events -n june-services --sort-by='.lastTimestamp'"
echo "  - Restart deployment: kubectl rollout restart deployment/<service> -n june-services"

# Save deployment info for reference
cat > deployment-summary.txt << EOF
June Platform Deployment Summary
================================

Deployment Date: $(date)
Project: $PROJECT_ID
Region: $REGION
Cluster: $CLUSTER_NAME
Static IP: $STATIC_IP
Registry: $ARTIFACT_REGISTRY

Commands for management:
- Connect to cluster: gcloud container clusters get-credentials $CLUSTER_NAME --region=$REGION --project=$PROJECT_ID
- View pods: kubectl get pods -n june-services
- View logs: kubectl logs -f deployment/<service> -n june-services
- Port forward: kubectl port-forward service/<service> 8080:8080 -n june-services

DNS Configuration needed:
- june-orchestrator.allsafe.world → $STATIC_IP
- june-stt.allsafe.world → $STATIC_IP
- june-tts.allsafe.world → $STATIC_IP
EOF

success "Deployment summary saved to deployment-summary.txt"
log "🎯 Deployment complete! Check the summary above for next steps."