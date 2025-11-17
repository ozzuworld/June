#!/bin/bash
# Build and deploy june-orchestrator with VPN support

set -e

echo "🔨 Building june-orchestrator Docker image..."

# Navigate to the build context
cd /home/user/June/June/services

# Build the image (note: build context is services/, not june-orchestrator/)
docker build \
  -f june-orchestrator/Dockerfile \
  -t docker.io/ozzuworld/june-orchestrator:latest \
  --platform linux/amd64 \
  .

echo "✅ Build complete!"
echo ""
echo "📤 Pushing to Docker Hub..."

docker push docker.io/ozzuworld/june-orchestrator:latest

echo "✅ Push complete!"
echo ""
echo "🔄 Restarting deployment in Kubernetes..."

kubectl rollout restart deployment/june-orchestrator -n june-services

echo "⏳ Waiting for deployment to be ready..."

kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Checking pod status..."
kubectl get pods -n june-services -l app=june-orchestrator

echo ""
echo "🧪 Testing the VPN endpoint..."
sleep 5

# Get a pod name
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

echo "Testing endpoint on pod: $POD"
kubectl exec -n june-services $POD -- curl -s http://localhost:8080/api/v1/device/config | head -20

echo ""
echo "🎉 All done! VPN API should now be accessible at:"
echo "   https://api.ozzu.world/api/v1/device/register"
