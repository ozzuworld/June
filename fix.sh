#!/bin/bash
# fix-orchestrator-build.sh - Fix the broken shared module import

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
PROJECT_ID="main-buffer-469817-v7"
REGION="us-central1"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/june"
IMAGE_TAG=$(date +%s)
NAMESPACE="june-services"

log "🔧 Fixing orchestrator container build"

# Step 1: Navigate to orchestrator directory
cd June/services/june-orchestrator || error "Cannot find June/services/june-orchestrator directory"

# Step 2: Backup current Dockerfile
if [[ -f "Dockerfile" ]]; then
    cp Dockerfile "Dockerfile.backup.$(date +%s)"
    success "Backed up current Dockerfile"
fi

# Step 3: Create fixed Dockerfile
log "Creating fixed Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app

# Copy shared module first (CRITICAL FIX)
COPY ../shared ./shared/

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set Python path to include shared module
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
EOF

success "Fixed Dockerfile created"

# Step 4: Configure Docker for GCP
log "Configuring Docker authentication..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# Step 5: Build new image
log "Building new container image..."
IMAGE_NAME="${REGISTRY}/june-orchestrator:${IMAGE_TAG}"
LATEST_IMAGE="${REGISTRY}/june-orchestrator:latest"

docker build -t "$IMAGE_NAME" -t "$LATEST_IMAGE" .
success "Container built successfully"

# Step 6: Push to registry
log "Pushing to container registry..."
docker push "$IMAGE_NAME"
docker push "$LATEST_IMAGE"
success "Image pushed to registry"

# Step 7: Update deployment to use new image
log "Updating Kubernetes deployment..."
kubectl set image deployment/june-orchestrator app="$IMAGE_NAME" -n $NAMESPACE
kubectl rollout restart deployment/june-orchestrator -n $NAMESPACE

# Step 8: Wait for rollout
log "Waiting for deployment to complete..."
kubectl rollout status deployment/june-orchestrator -n $NAMESPACE --timeout=300s
success "Deployment updated successfully"

# Step 9: Test the fix
log "Testing the shared module import..."
sleep 10  # Wait for pod to be ready

ORCHESTRATOR_POD=$(kubectl get pods -n $NAMESPACE -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')
log "Testing on pod: $ORCHESTRATOR_POD"

# Test shared module import
TEST_RESULT=$(kubectl exec $ORCHESTRATOR_POD -n $NAMESPACE -- python3 -c "
try:
    from shared.auth import AuthConfig
    config = AuthConfig.from_env()
    print('SUCCESS: Keycloak URL:', config.keycloak_url)
except Exception as e:
    print('FAILED:', e)
" 2>/dev/null || echo "FAILED: Pod not ready")

if [[ "$TEST_RESULT" == *"SUCCESS"* ]]; then
    success "Shared module import working!"
    echo "$TEST_RESULT"
else
    warning "Shared module import still failing: $TEST_RESULT"
fi

# Step 10: Check logs for localhost calls
log "Checking for localhost calls in recent logs..."
sleep 5
kubectl logs deployment/june-orchestrator -n $NAMESPACE --tail=20 | grep -E "(localhost|127.0.0.1)" || success "No localhost calls found in recent logs"

# Step 11: Summary
echo ""
echo "=============================="
echo "FIX SUMMARY"
echo "=============================="
echo ""
echo "✅ Actions completed:"
echo "  - Fixed Dockerfile to properly copy shared module"
echo "  - Built new container image: $IMAGE_NAME"
echo "  - Updated Kubernetes deployment"
echo "  - Deployment rolled out successfully"
echo ""
echo "🔍 Next steps:"
echo "  1. Test authentication:"
echo "     curl -X POST https://api.allsafe.world/v1/chat \\"
echo "          -H 'Authorization: Bearer YOUR_TOKEN' \\"
echo "          -H 'Content-Type: application/json' \\"
echo "          -d '{\"text\":\"test message\"}'"
echo ""
echo "  2. Monitor logs:"
echo "     kubectl logs deployment/june-orchestrator -n $NAMESPACE -f"
echo ""
echo "  3. Check if localhost calls are gone:"
echo "     kubectl logs deployment/june-orchestrator -n $NAMESPACE | grep localhost"
echo ""

if [[ "$TEST_RESULT" == *"SUCCESS"* ]]; then
    success "🎉 Container build fix completed successfully!"
else
    warning "⚠️ Fix applied but shared module import may still need debugging"
    echo ""
    echo "If import still fails, check:"
    echo "  - kubectl exec $ORCHESTRATOR_POD -n $NAMESPACE -- ls -la /app/shared/"
    echo "  - kubectl exec $ORCHESTRATOR_POD -n $NAMESPACE -- python3 -c 'import sys; print(sys.path)'"
fi