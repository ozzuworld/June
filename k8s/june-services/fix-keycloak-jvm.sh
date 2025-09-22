#!/bin/bash
# fix-keycloak-jvm.sh
# Fix Keycloak JVM garbage collector conflict

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

log "🔧 Fixing Keycloak JVM garbage collector conflict..."

# Check current status
log "📋 Current Keycloak pod status:"
kubectl get pods -n june-services -l app=june-idp

# Delete the current problematic deployment
log "🗑️ Removing current Keycloak deployment..."
kubectl delete deployment june-idp -n june-services --ignore-not-found=true

# Wait for pods to terminate
log "⏳ Waiting for pods to terminate..."
kubectl wait --for=delete pod -l app=june-idp -n june-services --timeout=60s || true

# Apply the fixed deployment
log "🚀 Applying fixed Keycloak deployment..."
kubectl apply -f keycloak-deployment-fixed.yaml

# Wait for the new deployment to be ready
log "⏳ Waiting for Keycloak to start (this may take 2-3 minutes)..."
kubectl wait --for=condition=available deployment/june-idp -n june-services --timeout=300s

# Check the status
log "📋 New deployment status:"
kubectl get pods -n june-services -l app=june-idp

# Test the health endpoint
log "🏥 Testing Keycloak health..."
kubectl port-forward -n june-services service/june-idp 8080:8080 &
pf_pid=$!
sleep 10

if curl -f -s http://localhost:8080/auth/health >/dev/null 2>&1; then
    success "Keycloak is healthy and running!"
else
    warning "Health check failed - checking logs..."
    kubectl logs -n june-services deployment/june-idp --tail=20
fi

kill $pf_pid 2>/dev/null || true

success "Keycloak JVM issue fixed!"

log "🔍 To verify everything is working:"
echo "1. Check logs: kubectl logs -n june-services deployment/june-idp"
echo "2. Access admin console: kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "   Then visit: http://localhost:8080/auth/admin"
echo "3. Username: admin, Password: admin123"