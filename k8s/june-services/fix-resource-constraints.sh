#!/bin/bash
# fix-resource-constraints.sh
# Fix Keycloak deployment for resource-constrained GKE Autopilot

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }

log "🔧 Fixing resource constraints for Keycloak deployment..."

# Check current cluster resources
log "📊 Checking cluster resources..."
echo "Node information:"
kubectl get nodes -o wide

echo ""
echo "Current resource usage:"
kubectl top nodes 2>/dev/null || echo "Metrics not available"

echo ""
echo "Pending pods:"
kubectl get pods --all-namespaces --field-selector=status.phase=Pending

# Clean up any stuck/pending pods
log "🧹 Cleaning up pending/failed pods..."
kubectl delete pods --field-selector=status.phase=Pending -n june-services --force --grace-period=0 2>/dev/null || true
kubectl delete pods --field-selector=status.phase=Failed -n june-services --force --grace-period=0 2>/dev/null || true

# Remove current Keycloak deployment if it exists
log "🗑️ Removing current Keycloak deployment..."
kubectl delete deployment june-idp -n june-services --ignore-not-found=true --force --grace-period=0

# Wait for cleanup
log "⏳ Waiting for cleanup..."
sleep 15

# Scale down other services temporarily to free resources
log "📉 Temporarily scaling down other services to free resources..."
kubectl scale deployment june-orchestrator -n june-services --replicas=0
kubectl scale deployment june-stt -n june-services --replicas=0  
kubectl scale deployment june-tts -n june-services --replicas=0

# Wait for scale down
log "⏳ Waiting for services to scale down..."
sleep 20

# Apply lightweight Keycloak
log "🚀 Deploying lightweight Keycloak..."
kubectl apply -f keycloak-lightweight.yaml

# Wait for Keycloak to be ready
log "⏳ Waiting for Keycloak to start (development mode is faster)..."
kubectl wait --for=condition=available deployment/june-idp -n june-services --timeout=300s

# Check Keycloak status
log "📋 Keycloak pod status:"
kubectl get pods -n june-services -l app=june-idp

# Test Keycloak health
log "🏥 Testing Keycloak health..."
sleep 30  # Give it extra time to fully start

kubectl port-forward -n june-services service/june-idp 8080:8080 &
pf_pid=$!
sleep 10

if curl -f -s http://localhost:8080/health >/dev/null 2>&1; then
    success "Keycloak is healthy!"
    
    # Test realm endpoint
    if curl -f -s http://localhost:8080/realms/june >/dev/null 2>&1; then
        success "June realm is accessible!"
    else
        warning "June realm not yet accessible (may still be starting)"
    fi
else
    warning "Keycloak health check failed - checking logs..."
    kubectl logs -n june-services deployment/june-idp --tail=20
fi

kill $pf_pid 2>/dev/null || true

# Scale services back up gradually
log "📈 Scaling services back up gradually..."

# Start with orchestrator (lightest)
kubectl scale deployment june-orchestrator -n june-services --replicas=1
kubectl wait --for=condition=available deployment/june-orchestrator -n june-services --timeout=120s
sleep 10

# Then TTS (proxy, lightweight)
kubectl scale deployment june-tts -n june-services --replicas=1
kubectl wait --for=condition=available deployment/june-tts -n june-services --timeout=120s
sleep 10

# Finally STT (heaviest)
kubectl scale deployment june-stt -n june-services --replicas=1
kubectl wait --for=condition=available deployment/june-stt -n june-services --timeout=180s

# Final status check
log "📋 Final deployment status:"
kubectl get pods -n june-services -o wide

log "💡 Resource optimization tips:"
echo "1. This uses Keycloak development mode (lighter, but not for production)"
echo "2. Much lower CPU/memory requests (100m CPU, 256Mi RAM)"
echo "3. Services scaled up gradually to avoid resource conflicts"
echo "4. For production, consider upgrading to a larger cluster"

success "Resource constraints fixed! All services should be running now."

log "🔍 To verify Keycloak is working:"
echo "kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "Then visit: http://localhost:8080/admin (admin/admin123)"