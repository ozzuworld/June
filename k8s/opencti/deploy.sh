#!/bin/bash
# OpenCTI Simple Deployment Script
# Deploys OpenCTI using Helm chart with existing OpenSearch

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Configuration
NS="opencti"
RELEASE="opencti"
CHART_REPO="https://devops-ia.github.io/helm-opencti"
CHART_NAME="opencti/opencti"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES_FILE="${SCRIPT_DIR}/values.yaml"

echo "=========================================="
log "OpenCTI Deployment"
echo "=========================================="
echo ""

# Verify prerequisites
log "Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    error "kubectl not found. Please install kubectl."
fi

if ! command -v helm &> /dev/null; then
    error "helm not found. Please install Helm 3.x."
fi

if ! kubectl cluster-info &> /dev/null; then
    error "Cannot connect to Kubernetes cluster."
fi

if [ ! -f "$VALUES_FILE" ]; then
    error "Values file not found: $VALUES_FILE"
fi

success "Prerequisites OK"

# Verify OpenSearch is running
log "Checking OpenSearch in 'default' namespace..."
if ! kubectl get service opensearch-cluster-master -n default &> /dev/null; then
    warn "OpenSearch service 'opensearch-cluster-master' not found in 'default' namespace"
    warn "OpenCTI will fail to start without OpenSearch"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Deployment cancelled"
    fi
else
    success "OpenSearch service found"
fi

# Add Helm repository
log "Adding Helm repository..."
helm repo add opencti "$CHART_REPO" >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1

success "Helm repository configured"

# Check if namespace exists
if kubectl get namespace "$NS" &> /dev/null; then
    log "Namespace '$NS' already exists"
else
    log "Creating namespace '$NS'..."
    kubectl create namespace "$NS"
fi

# Deploy OpenCTI
log "Deploying OpenCTI..."
log "  Namespace: $NS"
log "  Release: $RELEASE"
log "  Values: $VALUES_FILE"
echo ""

helm upgrade --install "$RELEASE" "$CHART_NAME" \
    --namespace "$NS" \
    --values "$VALUES_FILE" \
    --timeout 15m \
    --wait

echo ""
success "OpenCTI deployed successfully!"

# Show deployment status
echo ""
log "Deployment Status:"
kubectl get pods -n "$NS"

echo ""
log "Services:"
kubectl get services -n "$NS"

echo ""
log "Ingress:"
kubectl get ingress -n "$NS" 2>/dev/null || echo "No ingress configured"

# Show access information
echo ""
echo "=========================================="
success "OpenCTI is Ready!"
echo "=========================================="
echo ""
echo "📋 Access Information:"
echo "  URL: https://opencti.ozzu.world"
echo "  Email: admin@ozzu.world"
echo "  Password: Check values.yaml"
echo ""
echo "🔍 Useful Commands:"
echo "  # Check pods"
echo "  kubectl get pods -n $NS"
echo ""
echo "  # View logs"
echo "  kubectl logs -n $NS deployment/opencti-server -f"
echo ""
echo "  # Test OpenSearch connectivity"
echo "  kubectl exec -n $NS deployment/opencti-server -- \\"
echo "    curl http://opensearch-cluster-master.default.svc.cluster.local:9200"
echo ""
echo "=========================================="