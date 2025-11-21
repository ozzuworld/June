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

    # Import image into k3s containerd
    log "Importing image into k3s containerd..."
    docker save "${IMAGE_NAME}:${IMAGE_TAG}" -o /tmp/jellyfin-sso.tar

    if command -v k3s &> /dev/null; then
        sudo k3s ctr images import /tmp/jellyfin-sso.tar
        success "Image imported into k3s"
    else
        warn "k3s not found, skipping import (image only in Docker)"
    fi

    rm -f /tmp/jellyfin-sso.tar

    log "Image details:"
    docker images | grep jellyfin-sso

    echo ""
    echo "📦 Custom Jellyfin Image Ready"
    echo "  Image: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo "  Includes: SSO-Auth plugin v4.0.0.3"
    echo "  Available in: k3s containerd"
    echo ""
else
    error "Failed to build custom Jellyfin image"
fi

success "Jellyfin image build complete"
