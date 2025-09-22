#!/bin/bash
# deploy-june-platform.sh
# Complete deployment script for June AI Platform with Keycloak integration

set -euo pipefail

# Colors for output
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
ARTIFACT_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/june"

# Check prerequisites
check_prerequisites() {
    log "🔍 Checking prerequisites..."
    
    command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found"
    command -v kubectl >/dev/null 2>&1 || error "kubectl not found"
    command -v docker >/dev/null 2>&1 || error "docker not found"
    command -v terraform >/dev/null 2>&1 || error "terraform not found"
    
    # Check gcloud authentication
    gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 >/dev/null || error "gcloud not authenticated"
    
    success "Prerequisites check passed"
}

# Deploy infrastructure with Terraform
deploy_infrastructure() {
    log "🏗️ Deploying GKE infrastructure..."
    
    cd infra/gke
    
    # Initialize Terraform
    terraform init -upgrade
    
    # Plan and apply
    terraform plan \
        -var="project_id=${PROJECT_ID}" \
        -var="region=${REGION}" \
        -var="cluster_name=${CLUSTER_NAME}"
    
    terraform apply -auto-approve \
        -var="project_id=${PROJECT_ID}" \
        -var="region=${REGION}" \
        -var="cluster_name=${CLUSTER_NAME}"
    
    # Get cluster credentials
    gcloud container clusters get-credentials "${CLUSTER_NAME}" \
        --region="${REGION}" \
        --project="${PROJECT_ID}"
    
    cd ../..
    success "Infrastructure deployed"
}

# Setup Kubernetes secrets
setup_secrets() {
    log "🔐 Setting up Kubernetes secrets..."
    
    # Create namespace
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply secret manifests
    kubectl apply -f k8s/june-services/service-secrets.yaml
    
    success "Secrets configured"
}

# Build and push container images
build_images() {
    log "🐳 Building and pushing container images..."
    
    # Configure Docker for Artifact Registry
    gcloud auth configure-docker "${REGION}-docker.pkg.dev"
    
    # Services to build
    declare -A services=(
        ["june-orchestrator"]="June/services/june-orchestrator"
        ["june-stt"]="June/services/june-stt"
        ["june-tts"]="June/services/june-tts"
        ["june-idp"]="services/june-idp"
    )
    
    for service in "${!services[@]}"; do
        context="${services[$service]}"
        log "Building ${service} from ${context}..."
        
        # Build and tag images
        docker build -t "${ARTIFACT_REGISTRY}/${service}:latest" "${context}"
        docker build -t "${ARTIFACT_REGISTRY}/${service}:$(date +%s)" "${context}"
        
        # Push images
        docker push "${ARTIFACT_REGISTRY}/${service}:latest"
        docker push "${ARTIFACT_REGISTRY}/${service}:$(date +%s)"
        
        success "${service} image built and pushed"
    done
}

# Deploy Keycloak
deploy_keycloak() {
    log "🔑 Deploying Keycloak IDP..."
    
    # Apply Keycloak deployment
    kubectl apply -f k8s/june-services/keycloak-deployment.yaml
    
    # Wait for Keycloak to be ready
    log "Waiting for Keycloak to be ready..."
    kubectl wait --namespace june-services \
        --for=condition=available deployment/june-idp \
        --timeout=600s
    
    success "Keycloak deployed and ready"
}

# Deploy June services
deploy_services() {
    log "🚀 Deploying June AI services..."
    
    # Apply service deployments
    kubectl apply -f k8s/june-services/june-services-with-auth.yaml
    
    # Wait for all services to be ready
    log "Waiting for services to be ready..."
    kubectl wait --namespace june-services \
        --for=condition=available deployment \
        --selector=app \
        --timeout=600s
    
    success "June services deployed and ready"
}

# Deploy ingress and SSL
deploy_ingress() {
    log "🌐 Deploying ingress and SSL certificates..."
    
    # Apply managed certificates
    kubectl apply -f k8s/june-services/managedcert.yaml
    
    # Apply ingress
    kubectl apply -f k8s/june-services/ingress.yaml
    
    success "Ingress and SSL certificates configured"
}

# Update API keys
update_api_keys() {
    log "🔧 Updating API keys (if provided)..."
    
    if [[ -n "${GEMINI_API_KEY:-}" ]]; then
        kubectl patch secret june-secrets -n june-services \
            --patch="{\"data\":{\"GEMINI_API_KEY\":\"$(echo -n "${GEMINI_API_KEY}" | base64 -w 0)\"}}"
        success "Gemini API key updated"
    else
        warning "GEMINI_API_KEY not provided - please update manually"
    fi
    
    if [[ -n "${CHATTERBOX_API_KEY:-}" ]]; then
        kubectl patch secret june-secrets -n june-services \
            --patch="{\"data\":{\"CHATTERBOX_API_KEY\":\"$(echo -n "${CHATTERBOX_API_KEY}" | base64 -w 0)\"}}"
        success "Chatterbox API key updated"
    else
        warning "CHATTERBOX_API_KEY not provided - please update manually"
    fi
}

# Health check all services
health_check() {
    log "🏥 Performing health checks..."
    
    services=("june-idp" "june-orchestrator" "june-stt" "june-tts")
    
    for service in "${services[@]}"; do
        log "Checking ${service}..."
        
        # Port forward to check health
        kubectl port-forward -n june-services "service/${service}" 8080:8080 &
        pf_pid=$!
        sleep 5
        
        if curl -f http://localhost:8080/healthz >/dev/null 2>&1; then
            success "${service} is healthy"
        else
            warning "${service} health check failed"
        fi
        
        kill $pf_pid 2>/dev/null || true
        sleep 2
    done
}

# Get deployment info
get_deployment_info() {
    log "📋 Getting deployment information..."
    
    # Get static IP
    STATIC_IP=$(kubectl get ingress june-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "Pending...")
    
    # Get service endpoints
    echo ""
    echo "🎉 June AI Platform Deployment Complete!"
    echo ""
    echo "📋 Deployment Details:"
    echo "  Project: ${PROJECT_ID}"
    echo "  Region: ${REGION}"
    echo "  Cluster: ${CLUSTER_NAME}"
    echo "  Static IP: ${STATIC_IP}"
    echo "  Registry: ${ARTIFACT_REGISTRY}"
    echo ""
    echo "🌐 Service URLs (after DNS configuration):"
    echo "  • Keycloak Admin: https://june-idp.allsafe.world/auth/admin"
    echo "  • June Orchestrator: https://june-orchestrator.allsafe.world"
    echo "  • STT Service: https://june-stt.allsafe.world"
    echo "  • TTS Service: https://june-tts.allsafe.world"
    echo ""
    echo "🔧 DNS Configuration Required:"
    echo "  Point the following domains to: ${STATIC_IP}"
    echo "    june-idp.allsafe.world"
    echo "    june-orchestrator.allsafe.world"
    echo "    june-stt.allsafe.world"
    echo "    june-tts.allsafe.world"
    echo ""
    echo "🔑 Default Keycloak Admin Credentials:"
    echo "  Username: admin"
    echo "  Password: admin123"
    echo "  URL: https://june-idp.allsafe.world/auth/admin"
    echo ""
    echo "⚠️  Security Notes:"
    echo "  1. Change default Keycloak admin password"
    echo "  2. Update API keys in secrets if not already done"
    echo "  3. Review security settings for production use"
    echo ""
    echo "🧪 Testing:"
    echo "  Run: ./scripts/test-deployment.sh"
}

# Main deployment function
main() {
    log "🚀 Starting June AI Platform deployment..."
    log "📋 Project: ${PROJECT_ID} | Region: ${REGION} | Cluster: ${CLUSTER_NAME}"
    
    check_prerequisites
    deploy_infrastructure
    setup_secrets
    build_images
    deploy_keycloak
    deploy_services
    deploy_ingress
    update_api_keys
    health_check
    get_deployment_info
    
    success "Deployment completed successfully! 🎉"
}

# Run main function
main "$@"