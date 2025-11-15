#!/bin/bash
# Build and push Docker images for June Dark OSINT Framework

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

# Configuration
REGISTRY="${DOCKER_REGISTRY:-ghcr.io/ozzuworld}"
TAG="${DOCKER_TAG:-latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
JUNE_DARK_DIR="${ROOT_DIR}/June/services"

log "Building June Dark Docker images..."
log "Registry: ${REGISTRY}"
log "Tag: ${TAG}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    error "Docker is not running"
fi

# Build Orchestrator
log "Building Orchestrator..."
docker build -t ${REGISTRY}/june-dark-orchestrator:${TAG} \
    ${JUNE_DARK_DIR}/june-dark/services/orchestrator

success "Orchestrator built"

# Build Collector
log "Building Collector..."
docker build -t ${REGISTRY}/june-dark-collector:${TAG} \
    ${JUNE_DARK_DIR}/june-dark/services/collector

success "Collector built"

# Build Enricher
log "Building Enricher..."
docker build -t ${REGISTRY}/june-dark-enricher:${TAG} \
    ${JUNE_DARK_DIR}/june-dark/services/enricher

success "Enricher built"

# Build Ops UI
log "Building Ops UI..."
docker build -t ${REGISTRY}/june-dark-ops-ui:${TAG} \
    ${JUNE_DARK_DIR}/june-dark/services/ops-ui

success "Ops UI built"

# Build OpenCTI Connector
log "Building OpenCTI Connector..."
docker build -t ${REGISTRY}/june-dark-opencti-connector:${TAG} \
    ${JUNE_DARK_DIR}/june-dark-opencti-connector

success "OpenCTI Connector built"

# List built images
log "Built images:"
docker images | grep june-dark

# Ask to push
read -p "Push images to registry? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log "Pushing images to ${REGISTRY}..."

    docker push ${REGISTRY}/june-dark-orchestrator:${TAG}
    docker push ${REGISTRY}/june-dark-collector:${TAG}
    docker push ${REGISTRY}/june-dark-enricher:${TAG}
    docker push ${REGISTRY}/june-dark-ops-ui:${TAG}
    docker push ${REGISTRY}/june-dark-opencti-connector:${TAG}

    success "All images pushed successfully!"
else
    warn "Images not pushed. Run manually when ready:"
    echo "  docker push ${REGISTRY}/june-dark-orchestrator:${TAG}"
    echo "  docker push ${REGISTRY}/june-dark-collector:${TAG}"
    echo "  docker push ${REGISTRY}/june-dark-enricher:${TAG}"
    echo "  docker push ${REGISTRY}/june-dark-ops-ui:${TAG}"
    echo "  docker push ${REGISTRY}/june-dark-opencti-connector:${TAG}"
fi

success "Build complete!"
