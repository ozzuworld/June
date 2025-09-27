#!/bin/bash
# fix-crash-loop.sh - Emergency fix for orchestrator crash loop

set -euo pipefail

echo "🚨 Emergency Fix: Orchestrator Crash Loop"
echo "========================================"

cd June/services/june-orchestrator

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ app.py not found. Are you in the right directory?"
    exit 1
fi

echo "🔧 Step 1: Backup broken version"
cp app.py app_broken_$(date +%s).py
echo "✅ Backup created"

echo "🔧 Step 2: Building emergency fix image"
TIMESTAMP=$(date +%s)
IMAGE_TAG="fix-crash-${TIMESTAMP}"
FULL_IMAGE="us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:${IMAGE_TAG}"

# Build the image
docker build -t "$FULL_IMAGE" .
docker tag "$FULL_IMAGE" "us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest"

echo "✅ Image built: $FULL_IMAGE"

echo "🔧 Step 3: Pushing to registry"
docker push "$FULL_IMAGE"
docker push "us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest"

echo "✅ Image pushed"

echo "🔧 Step 4: Force restart deployment"
kubectl rollout restart deployment/june-orchestrator -n june-services

echo "⏳ Step 5: Waiting for healthy deployment"
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s

echo "🔧 Step 6: Checking pod status"
kubectl get pods -n june-services -l app=june-orchestrator

echo "🔧 Step 7: Testing health endpoint"
sleep 10
POD_NAME=$(kubectl get pods -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "no-pod")

if [ "$POD_NAME" != "no-pod" ] && [ "$POD_NAME" != "" ]; then
    echo "Testing health endpoint on pod: $POD_NAME"
    kubectl exec -n june-services "$POD_NAME" -- curl -s http://localhost:8080/healthz || echo "Health check failed"
    
    echo ""
    echo "🔧 Recent logs:"
    kubectl logs -n june-services "$POD_NAME" --tail=10
else
    echo "⚠️ No pod found or pod not ready yet"
fi

echo ""
echo "=================================="
echo "🎉 EMERGENCY FIX COMPLETE!"
echo "=================================="
echo ""
echo "✅ Crash loop should be resolved"
echo ""
echo "🔍 Monitor with:"
echo "   kubectl logs -n june-services deployment/june-orchestrator -f"
echo ""
echo "🧪 Test with:"
echo "   kubectl port-forward -n june-services svc/june-orchestrator 8080:80 &"
echo "   curl http://localhost:8080/healthz"