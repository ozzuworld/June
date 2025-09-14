#!/usr/bin/env bash
# scripts/deploy-kokoro-tts.sh
# Deploy Kokoro TTS service to Cloud Run

set -euo pipefail

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="june-kokoro-tts"
IMAGE_TAG="${IMAGE_TAG:-latest}"
AR_REPO="${AR_REPO:-june}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
    exit 1
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    if ! command -v gcloud &> /dev/null; then
        error "gcloud CLI not found. Please install Google Cloud SDK."
    fi
    
    if ! command -v docker &> /dev/null; then
        error "Docker not found. Please install Docker."
    fi
    
    # Check if authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        error "Not authenticated with gcloud. Run 'gcloud auth login' first."
    fi
    
    success "Prerequisites check passed"
}

# Build and push the Docker image
build_and_push() {
    log "Building and pushing Kokoro TTS Docker image..."
    
    local image_name="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:${IMAGE_TAG}"
    local build_path="June/services/june-kokoro-tts"
    
    if [[ ! -d "$build_path" ]]; then
        error "Build path not found: $build_path"
    fi
    
    # Configure Docker for Artifact Registry
    gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
    
    # Build the image
    log "Building image: $image_name"
    docker build -t "$image_name" "$build_path"
    
    # Push the image
    log "Pushing image to Artifact Registry..."
    docker push "$image_name"
    
    success "Image built and pushed: $image_name"
    echo "$image_name"
}

# Deploy to Cloud Run
deploy_service() {
    local image_name="$1"
    
    log "Deploying Kokoro TTS service to Cloud Run..."
    
    # Set environment variables
    local env_vars=""
    env_vars+="KC_BASE_URL=${KC_BASE_URL:-https://june-idp-359243954.us-central1.run.app},"
    env_vars+="KC_REALM=${KC_REALM:-june},"
    env_vars+="MODEL_PATH=/app/models,"
    env_vars+="DEVICE=cpu,"
    env_vars+="LOG_LEVEL=INFO"
    
    # Remove trailing comma
    env_vars="${env_vars%,}"
    
    # Deploy the service
    gcloud run deploy "$SERVICE_NAME" \
        --image="$image_name" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --cpu="2" \
        --memory="4Gi" \
        --min-instances="0" \
        --max-instances="5" \
        --timeout="900" \
        --concurrency="2" \
        --service-account="kokoro-tts-svc@${PROJECT_ID}.iam.gserviceaccount.com" \
        --allow-unauthenticated \
        --set-env-vars="$env_vars" \
        --execution-environment="gen2" \
        --platform="managed"
    
    # Get the service URL
    local service_url
    service_url=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.uri)')
    
    success "Service deployed successfully!"
    log "Service URL: $service_url"
    
    return 0
}

# Test the deployed service
test_service() {
    local service_url
    service_url=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.uri)' 2>/dev/null || echo "")
    
    if [[ -z "$service_url" ]]; then
        warning "Could not get service URL for testing"
        return 1
    fi
    
    log "Testing deployed service..."
    
    # Test health endpoint
    log "Testing health endpoint: $service_url/healthz"
    if curl -s -f "$service_url/healthz" > /dev/null; then
        success "Health check passed"
    else
        warning "Health check failed"
    fi
    
    # Test voices endpoint
    log "Testing voices endpoint: $service_url/v1/voices"
    if curl -s -f "$service_url/v1/voices" > /dev/null; then
        success "Voices endpoint accessible"
        
        # Show available voices
        log "Available voices:"
        curl -s "$service_url/v1/voices" | jq -r '.voices | keys[]' 2>/dev/null || echo "Could not parse voices"
    else
        warning "Voices endpoint not accessible"
    fi
}

# Update orchestrator configuration
update_orchestrator() {
    local kokoro_url
    kokoro_url=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.uri)' 2>/dev/null || echo "")
    
    if [[ -z "$kokoro_url" ]]; then
        warning "Could not get Kokoro TTS URL for orchestrator update"
        return 1
    fi
    
    log "Updating orchestrator to use Kokoro TTS..."
    
    # Update orchestrator environment variables
    gcloud run services update "june-orchestrator" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --update-env-vars="TTS_SERVICE_URL=$kokoro_url" \
        --quiet
    
    success "Orchestrator updated to use Kokoro TTS: $kokoro_url"
}

# Main deployment flow
main() {
    log "Starting Kokoro TTS deployment..."
    
    check_prerequisites
    
    local image_name
    image_name=$(build_and_push)
    
    deploy_service "$image_name"
    
    # Wait a moment for the service to be ready
    log "Waiting for service to be ready..."
    sleep 10
    
    test_service
    
    # Optionally update orchestrator
    if [[ "${UPDATE_ORCHESTRATOR:-true}" == "true" ]]; then
        update_orchestrator
    fi
    
    success "Kokoro TTS deployment completed!"
    
    # Show summary
    local service_url
    service_url=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.uri)' 2>/dev/null || echo "Unknown")
    
    echo ""
    log "🎉 Deployment Summary:"
    echo "   Service: $SERVICE_NAME"
    echo "   URL: $service_url"
    echo "   Region: $REGION"
    echo "   Project: $PROJECT_ID"
    echo ""
    log "🧪 Test endpoints:"
    echo "   Health: $service_url/healthz"
    echo "   Voices: $service_url/v1/voices"
    echo ""
    log "📝 Next steps:"
    echo "   1. Set up Keycloak client credentials for kokoro-service"
    echo "   2. Update KOKORO_CLIENT_ID and KOKORO_CLIENT_SECRET in GitHub secrets"
    echo "   3. Test voice synthesis with authenticated requests"
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "test")
        test_service
        ;;
    "update-orch")
        update_orchestrator
        ;;
    "build")
        build_and_push
        ;;
    *)
        echo "Usage: $0 [deploy|test|update-orch|build]"
        echo ""
        echo "Commands:"
        echo "  deploy      - Full deployment (default)"
        echo "  test        - Test existing deployment"
        echo "  update-orch - Update orchestrator to use Kokoro TTS"
        echo "  build       - Only build and push image"
        exit 1
        ;;
esac