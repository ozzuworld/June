#!/bin/bash
set -e

echo "🔧 Applying LiveKit integration fixes (Quick Method)..."

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}📋 Quick Fix Summary:${NC}"
echo "1. Orchestrator already updated with new LiveKit SDK"
echo "2. Applying ingress fixes directly via kubectl"
echo "3. Creating LiveKit proxy service"
echo "4. Testing the fixes"
echo ""

# Step 1: Create the LiveKit proxy service (cross-namespace access)
echo -e "${YELLOW}🔄 Step 1: Creating LiveKit proxy service...${NC}"

# Delete existing proxy service if it exists
kubectl delete service livekit-proxy -n june-services --ignore-not-found=true

# Create the proxy service to access LiveKit in media namespace
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: livekit-proxy
  namespace: june-services
spec:
  type: ExternalName
  externalName: livekit-livekit-server.media.svc.cluster.local
  ports:
  - name: http
    port: 80
    targetPort: 80
    protocol: TCP
EOF

echo -e "${GREEN}✅ LiveKit proxy service created${NC}"

# Step 2: Update the ingress to use the proxy and correct domain
echo -e "${YELLOW}🔄 Step 2: Updating ingress configuration...${NC}"

# Update the ingress to point to livekit.ozzu.world and use the proxy service
kubectl patch ingress june-ingress -n june-services --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/rules/1",
    "value": {
      "host": "livekit.ozzu.world",
      "http": {
        "paths": [
          {
            "path": "/",
            "pathType": "Prefix",
            "backend": {
              "service": {
                "name": "livekit-proxy",
                "port": {
                  "number": 80
                }
              }
            }
          }
        ]
      }
    }
  }
]'

echo -e "${GREEN}✅ Ingress configuration updated${NC}"

# Step 3: Update ingress annotations for WebSocket support
echo -e "${YELLOW}🔄 Step 3: Adding WebSocket support annotations...${NC}"

kubectl annotate ingress june-ingress -n june-services \
  nginx.ingress.kubernetes.io/websocket-services="livekit-proxy" \
  --overwrite

kubectl annotate ingress june-ingress -n june-services \
  nginx.ingress.kubernetes.io/proxy-buffering="off" \
  --overwrite

kubectl annotate ingress june-ingress -n june-services \
  nginx.ingress.kubernetes.io/proxy-request-buffering="off" \
  --overwrite

echo -e "${GREEN}✅ WebSocket annotations added${NC}"

# Step 4: Verify services and wait for propagation
echo -e "${YELLOW}🔍 Step 4: Verifying configuration...${NC}"

echo "Checking orchestrator pods..."
kubectl get pods -n june-services -l app=june-orchestrator

echo "Checking LiveKit pod in media namespace..."
kubectl get pods -n media -l app.kubernetes.io/name=livekit-server

echo "Checking proxy service..."
kubectl get services -n june-services livekit-proxy

echo "Checking updated ingress..."
kubectl get ingress june-ingress -n june-services -o jsonpath='{.spec.rules[1]}' | jq .

# Wait for ingress to propagate
echo "Waiting 30 seconds for ingress changes to propagate..."
sleep 30

# Step 5: Test the fixes
echo -e "${YELLOW}🧪 Step 5: Testing the fixes...${NC}"

echo "Testing orchestrator API (should return 200 with valid token)..."
if curl -f -s https://api.ozzu.world/api/sessions/ \
    -H 'Content-Type: application/json' \
    -d '{"user_id":"test","room_name":"test-room"}' > /dev/null; then
    echo -e "${GREEN}✅ Orchestrator API test passed${NC}"
    
    # Show a sample response
    echo "Sample response:"
    curl -s https://api.ozzu.world/api/sessions/ \
        -H 'Content-Type: application/json' \
        -d '{"user_id":"test","room_name":"test-room"}' | jq .
else
    echo -e "${RED}❌ Orchestrator API test failed${NC}"
    echo "Checking orchestrator logs:"
    kubectl logs -n june-services -l app=june-orchestrator --tail=20
fi

echo ""
echo "Testing LiveKit endpoint (should return 200 OK, not 503)..."
LIVEKIT_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" https://livekit.ozzu.world/)
if [ "$LIVEKIT_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✅ LiveKit endpoint test passed (HTTP $LIVEKIT_RESPONSE)${NC}"
else
    echo -e "${RED}❌ LiveKit endpoint test failed (HTTP $LIVEKIT_RESPONSE)${NC}"
    if [ "$LIVEKIT_RESPONSE" = "503" ]; then
        echo "Still getting 503 - checking proxy service and LiveKit pod:"
        kubectl describe service livekit-proxy -n june-services
        echo ""
        kubectl logs -n media -l app.kubernetes.io/name=livekit-server --tail=10
    fi
fi

echo ""
echo -e "${BLUE}🎉 Quick fix application completed!${NC}"
echo ""
echo -e "${GREEN}Verification commands:${NC}"
echo "curl -i https://api.ozzu.world/api/sessions/ -H 'Content-Type: application/json' -d '{\"user_id\":\"test\",\"room_name\":\"test-room\"}'"
echo "curl -i https://livekit.ozzu.world/"
echo ""
echo -e "${YELLOW}If issues persist, check:${NC}"
echo "kubectl logs -n june-services -l app=june-orchestrator --tail=50"
echo "kubectl logs -n media -l app.kubernetes.io/name=livekit-server --tail=50"
echo "kubectl describe ingress june-ingress -n june-services"
echo ""