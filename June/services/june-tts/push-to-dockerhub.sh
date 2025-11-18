#!/bin/bash
set -e

# Configuration
DOCKERHUB_USER="ozzuworld"
IMAGE_NAME="june-tts-orpheus"
LOCAL_IMAGE="june-tts:orpheus"
VERSION="v1.0"

echo "================================================================================"
echo "🐳 Pushing Orpheus TTS to Docker Hub"
echo "================================================================================"

# Check if local image exists
if ! docker image inspect "$LOCAL_IMAGE" > /dev/null 2>&1; then
    echo "❌ Error: Local image '$LOCAL_IMAGE' not found!"
    echo "Available images:"
    docker images
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
echo "================================================================================"
