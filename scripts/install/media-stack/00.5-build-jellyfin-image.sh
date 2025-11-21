#!/bin/bash
# Media Stack - Build Custom Jellyfin Image with SSO Plugin
# Builds a custom Jellyfin image with SSO plugin pre-installed

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Please run from June project directory"
fi

log "Building custom Jellyfin image with SSO plugin"

DOCKERFILE_DIR="${ROOT_DIR}/docker/jellyfin-sso"
IMAGE_NAME="jellyfin-sso"
IMAGE_TAG="latest"

# Check if Dockerfile exists
if [ ! -f "${DOCKERFILE_DIR}/Dockerfile" ]; then
    error "Dockerfile not found at: ${DOCKERFILE_DIR}/Dockerfile"
fi

# Build the image
log "Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
cd "$DOCKERFILE_DIR"

docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

if [ $? -eq 0 ]; then
    success "Custom Jellyfin image built successfully"

    # Tag for local k8s use
    docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "localhost:5000/${IMAGE_NAME}:${IMAGE_TAG}" || true

    log "Image details:"
    docker images | grep jellyfin-sso

    echo ""
    echo "📦 Custom Jellyfin Image Ready"
    echo "  Image: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo "  Includes: SSO-Auth plugin v4.0.0.3"
    echo ""
else
    error "Failed to build custom Jellyfin image"
fi

success "Jellyfin image build complete"
