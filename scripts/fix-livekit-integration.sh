#!/bin/bash
set -e

echo "🔧 Applying LiveKit integration fixes..."

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}📋 Fix Summary:${NC}"
echo "1. Updated LiveKit SDK to version 0.8.0"
echo "2. Fixed VideoGrants API usage"
echo "3. Updated ingress configuration for cross-namespace access"
echo "4. Added LiveKit proxy service for proper routing"
echo ""

# Step 1: Rebuild and redeploy orchestrator with updated code
echo -e "${YELLOW}🔄 Step 1: Rebuilding orchestrator with updated LiveKit SDK...${NC}"

# Check if we're in the right directory
if [ ! -f "June/services/june-orchestrator/Dockerfile" ]; then
    echo -e "${RED}❌ Error: Please run this script from the June repository root${NC}"
    exit 1
fi

# Build new orchestrator image
echo "Building updated orchestrator image..."
cd June/services/june-orchestrator
docker build -t ozzuworld/june-orchestrator:livekit-fix .
docker tag ozzuworld/june-orchestrator:livekit-fix ozzuworld/june-orchestrator:latest

# Push to registry
echo "Pushing updated image to registry..."
docker push ozzuworld/june-orchestrator:latest
docker push ozzuworld/june-orchestrator:livekit-fix

cd ../../..

# Step 2: Update the deployment
echo -e "${YELLOW}🔄 Step 2: Updating orchestrator deployment...${NC}"

# Force pull new image
kubectl rollout restart deployment/june-orchestrator -n june-services

# Wait for deployment to complete
echo "Waiting for orchestrator rollout to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s

# Step 3: Apply ingress fixes
echo -e "${YELLOW}🔄 Step 3: Applying ingress configuration fixes...${NC}"

# Delete existing proxy service if it exists (to recreate with correct config)
echo "Cleaning up existing proxy service..."
kubectl delete service livekit-proxy -n june-services --ignore-not-found=true

# Apply updated ingress (this will recreate the proxy service)
echo "Applying updated Helm configuration..."
helm upgrade june-platform ./helm/june-platform \
  --namespace june-services \
  --set secrets.geminiApiKey="${GEMINI_API_KEY:-}" \
  --set secrets.cloudflareToken="${CLOUDFLARE_TOKEN:-}" \
  --reuse-values

# Step 4: Verify services
echo -e "${YELLOW}🔍 Step 4: Verifying service status...${NC}"

echo "Checking orchestrator pods..."
kubectl get pods -n june-services -l app=june-orchestrator

echo "Checking LiveKit pod in media namespace..."
kubectl get pods -n media -l app.kubernetes.io/name=livekit-server

echo "Checking services..."
kubectl get services -n june-services livekit-proxy
kubectl get services -n media livekit-livekit-server

echo "Checking ingress..."
kubectl get ingress june-ingress -n june-services

# Step 5: Test the fixes
echo -e "${YELLOW}🧪 Step 5: Testing the fixes...${NC}"

# Wait a moment for services to be ready
sleep 10

echo "Testing orchestrator API (should return 200 with valid token)..."
if curl -f -s https://api.ozzu.world/api/sessions/ \
    -H 'Content-Type: application/json' \
    -d '{"user_id":"test","room_name":"test-room"}' > /dev/null; then
    echo -e "${GREEN}✅ Orchestrator API test passed${NC}"
else
    echo -e "${RED}❌ Orchestrator API test failed${NC}"
    echo "Run: kubectl logs -n june-services -l app=june-orchestrator --tail=50"
fi

echo "Testing LiveKit endpoint (should return 200 OK, not 503)..."
if curl -f -s https://livekit.ozzu.world/ > /dev/null; then
    echo -e "${GREEN}✅ LiveKit endpoint test passed${NC}"
else
    echo -e "${RED}❌ LiveKit endpoint test failed${NC}"
    echo "Run: kubectl logs -n media -l app.kubernetes.io/name=livekit-server --tail=50"
fi

echo ""
echo -e "${BLUE}🎉 Fix application completed!${NC}"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Test your June orchestrator API at: https://api.ozzu.world/api/sessions/"
echo "2. Verify LiveKit is accessible at: https://livekit.ozzu.world/"
echo "3. Monitor logs if issues persist:"
echo "   - Orchestrator: kubectl logs -n june-services -l app=june-orchestrator --tail=50"
echo "   - LiveKit: kubectl logs -n media -l app.kubernetes.io/name=livekit-server --tail=50"
echo ""
echo -e "${YELLOW}Manual verification commands:${NC}"
echo "curl -i https://api.ozzu.world/api/sessions/ -H 'Content-Type: application/json' -d '{\"user_id\":\"test\",\"room_name\":\"test-room\"}'"
echo "curl -i https://livekit.ozzu.world/"
echo ""