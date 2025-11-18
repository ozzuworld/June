#!/bin/bash
set -e

# Configuration
DOCKERHUB_USER="ozzuworld"
IMAGE_NAME="june-tts"
LOCAL_IMAGE="june-tts:latest"
VERSION="v1.0"
BUILD_IMAGE=${1:-false}

echo "================================================================================"
echo "🐳 Building and Pushing June TTS (Orpheus) to Docker Hub"
echo "================================================================================"

# Build image if requested
if [ "$BUILD_IMAGE" = "build" ] || [ "$BUILD_IMAGE" = "true" ]; then
    echo "🔨 Building Docker image..."
    docker build -t "$LOCAL_IMAGE" .
    echo "✅ Build complete"
    echo ""
fi

# Check if local image exists
if ! docker image inspect "$LOCAL_IMAGE" > /dev/null 2>&1; then
    echo "❌ Error: Local image '$LOCAL_IMAGE' not found!"
    echo ""
    echo "Available images:"
    docker images
    echo ""
    echo "To build the image first, run:"
    echo "   ./push-to-dockerhub.sh build"
    exit 1
fi

echo "✅ Found local image: $LOCAL_IMAGE"

# Tag for Docker Hub
echo "📦 Tagging image for Docker Hub..."
docker tag "$LOCAL_IMAGE" "${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
docker tag "$LOCAL_IMAGE" "${DOCKERHUB_USER}/${IMAGE_NAME}:${VERSION}"

echo "✅ Tagged as:"
echo "   - ${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
echo "   - ${DOCKERHUB_USER}/${IMAGE_NAME}:${VERSION}"

# Push to Docker Hub
echo ""
echo "🚀 Pushing to Docker Hub..."
docker push "${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
docker push "${DOCKERHUB_USER}/${IMAGE_NAME}:${VERSION}"

echo ""
echo "================================================================================"
echo "✅ Successfully pushed to Docker Hub!"
echo "================================================================================"
echo ""
echo "To pull this image:"
echo "   docker pull ${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
echo "   docker pull ${DOCKERHUB_USER}/${IMAGE_NAME}:${VERSION}"
echo ""
echo "Image details:"
echo "   Repository: https://hub.docker.com/r/${DOCKERHUB_USER}/${IMAGE_NAME}"
echo "   Tags: latest, ${VERSION}"
echo "   Size: $(docker images --format "{{.Size}}" "$LOCAL_IMAGE")"
echo ""
echo "Configuration:"
echo "   - Model: Orpheus Multilingual TTS (canopylabs/orpheus-3b-0.1-ft)"
echo "   - VRAM Usage: ~8GB (50% GPU utilization)"
echo "   - Concurrent Sessions: 15x capacity"
echo "   - Latency: 100-200ms"
echo "================================================================================"
