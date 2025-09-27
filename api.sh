#!/bin/bash
# Fixed rebuild script for orchestrator

echo "🔨 Rebuilding orchestrator with fixed Dockerfile..."

cd June/services/june-orchestrator

# 4. Build new container image
echo "🐳 Building new container image..."
docker build -t us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:$(date +%s) .
docker tag us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:$(date +%s) us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest

# 5. Push to registry
echo "📤 Pushing to registry..."
docker push us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest

# 6. Force restart deployment
echo "🔄 Restarting deployment..."
kubectl rollout restart deployment/june-orchestrator -n june-services

# 7. Wait for rollout
echo "⏳ Waiting for rollout to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s

echo "✅ Rebuild complete! Check logs:"
echo "kubectl logs deployment/june-orchestrator -n june-services -f"


kubectl create deployment june-orchestrator --image=us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest -n june-services