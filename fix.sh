#!/bin/bash
# deploy-fixed-orchestrator.sh

set -euo pipefail

echo "🔧 Deploying Fixed Orchestrator with Gemini Integration"
echo "======================================================="

NAMESPACE="june-services"
PROJECT_ID="main-buffer-469817-v7"
REGION="us-central1"

# Step 1: Check if Gemini API key is properly set in Kubernetes
echo "📝 Step 1: Checking Gemini API key in Kubernetes..."

# Check if secret exists
if kubectl get secret june-secrets -n $NAMESPACE &>/dev/null; then
    echo "✅ Secret 'june-secrets' exists"
    
    # Check if gemini-api-key is present
    KEY_EXISTS=$(kubectl get secret june-secrets -n $NAMESPACE -o jsonpath='{.data.gemini-api-key}' 2>/dev/null || echo "")
    
    if [ -z "$KEY_EXISTS" ]; then
        echo "❌ No gemini-api-key in secret"
        
        # Read from .env file if exists
        if [ -f "June/services/june-orchestrator/.env" ]; then
            GEMINI_KEY=$(grep "^GEMINI_API_KEY=" June/services/june-orchestrator/.env | cut -d'=' -f2)
            
            if [ ! -z "$GEMINI_KEY" ]; then
                echo "📋 Found API key in .env file, creating secret..."
                kubectl create secret generic june-secrets \
                    --from-literal=gemini-api-key="$GEMINI_KEY" \
                    -n $NAMESPACE \
                    --dry-run=client -o yaml | kubectl apply -f -
                echo "✅ Secret updated with Gemini API key"
            else
                echo "⚠️ No API key found in .env file"
                echo "🔑 Please get an API key from: https://makersuite.google.com/app/apikey"
                echo "   Then run: kubectl create secret generic june-secrets --from-literal=gemini-api-key='YOUR_KEY' -n $NAMESPACE"
            fi
        fi
    else
        DECODED_KEY=$(echo "$KEY_EXISTS" | base64 -d 2>/dev/null | head -c 20)
        echo "✅ Gemini API key is set (starts with: ${DECODED_KEY}...)"
    fi
else
    echo "❌ Secret 'june-secrets' does not exist"
    echo "Creating secret..."
    
    # Try to read from .env
    if [ -f "June/services/june-orchestrator/.env" ]; then
        GEMINI_KEY=$(grep "^GEMINI_API_KEY=" June/services/june-orchestrator/.env | cut -d'=' -f2)
        
        if [ ! -z "$GEMINI_KEY" ]; then
            kubectl create secret generic june-secrets \
                --from-literal=gemini-api-key="$GEMINI_KEY" \
                -n $NAMESPACE
            echo "✅ Secret created with Gemini API key"
        fi
    fi
fi

# Step 2: Copy the fixed app.py
echo -e "\n📝 Step 2: Updating orchestrator code..."
# The app.py content should be saved from above

# Step 3: Build and deploy
echo -e "\n🐳 Step 3: Building and deploying..."

cd June/services/june-orchestrator

# Configure Docker
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build with timestamp
TIMESTAMP=$(date +%s)
IMAGE_TAG="gemini-fix-${TIMESTAMP}"
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/june/june-orchestrator:${IMAGE_TAG}"

echo "Building image: $FULL_IMAGE"
docker build -t "$FULL_IMAGE" .
docker push "$FULL_IMAGE"

# Update deployment
kubectl set image deployment/june-orchestrator orchestrator=$FULL_IMAGE -n $NAMESPACE

# Wait for rollout
kubectl rollout status deployment/june-orchestrator -n $NAMESPACE --timeout=300s

echo -e "\n✅ Deployment complete!"

# Step 4: Test the deployment
echo -e "\n🧪 Step 4: Testing deployment..."

# Wait for pod to be ready
sleep 10

# Test internal endpoints
POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

echo "Testing Gemini status..."
kubectl exec -n $NAMESPACE $POD_NAME -- curl -s http://localhost:8080/debug/gemini | jq '.' || echo "Raw response"

echo -e "\nTesting chat endpoint..."
kubectl exec -n $NAMESPACE $POD_NAME -- curl -s -X POST http://localhost:8080/debug/test-chat | jq '.' || echo "Raw response"

echo -e "\n=================================="
echo "DEPLOYMENT COMPLETE"
echo "=================================="
echo ""
echo "✅ Fixed orchestrator deployed with:"
echo "  • Enhanced Gemini integration"
echo "  • Better error handling and logging"
echo "  • Debug endpoints for troubleshooting"
echo "  • Automatic model fallback"
echo ""
echo "🧪 Test endpoints:"
echo "  • curl https://api.allsafe.world/debug/gemini"
echo "  • curl -X POST https://api.allsafe.world/debug/test-chat"
echo "  • curl -X POST https://api.allsafe.world/v1/chat -H 'Content-Type: application/json' -d '{\"text\":\"Hello\"}"
echo ""
echo "📋 Check logs:"
echo "  kubectl logs -n june-services deployment/june-orchestrator -f"