#!/bin/bash
# Check what's actually in your registry and fix the deployment

echo "🔍 Checking what images are in your registry..."

# List all available images
gcloud artifacts docker images list us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator

echo -e "\n🔍 Checking current deployment image reference..."
kubectl get deployment june-orchestrator -n june-services -o jsonpath='{.spec.template.spec.containers[0].image}'
echo ""

echo -e "\n🔧 Fixing deployment to use latest tag..."
kubectl patch deployment june-orchestrator -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "app",
          "image": "us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest"
        }]
      }
    }
  }
}'

echo "✅ Updated deployment to use :latest tag"

# Do the same for STT service
echo -e "\n🔧 Fixing STT deployment to use correct image..."
kubectl patch deployment june-stt -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "app", 
          "image": "us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-stt:latest"
        }]
      }
    }
  }
}'

echo "✅ Updated STT deployment to use :latest tag"