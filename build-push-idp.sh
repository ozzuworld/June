#!/bin/bash
# build-push-idp.sh - Build and push IDP image
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
IMAGE_NAME="june-idp"
REGISTRY_URL="$REGION-docker.pkg.dev/$PROJECT_ID/june"

echo "🐳 Building and pushing $IMAGE_NAME image"
echo "========================================="
echo "Project: $PROJECT_ID"
echo "Registry: $REGISTRY_URL"
echo ""

# Step 1: Authenticate Docker to Artifact Registry
echo "1. Authenticating Docker..."
gcloud auth configure-docker $REGION-docker.pkg.dev

# Step 2: Build the image
echo "2. Building image..."
cd services/june-idp
docker build -t $IMAGE_NAME:latest .

# Step 3: Tag for Artifact Registry
echo "3. Tagging image..."
docker tag $IMAGE_NAME:latest $REGISTRY_URL/$IMAGE_NAME:latest

# Step 4: Push to registry
echo "4. Pushing image..."
docker push $REGISTRY_URL/$IMAGE_NAME:latest

echo ""
echo "✅ Image pushed successfully!"
echo "   Image: $REGISTRY_URL/$IMAGE_NAME:latest"
echo ""
echo "🔄 Now restart the deployment:"
echo "   kubectl rollout restart deployment/june-idp -n june-services"