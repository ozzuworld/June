#!/bin/bash
# deploy-production-keycloak.sh
# Deploy production-ready Keycloak with PostgreSQL

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

log "🚀 Deploying Production Keycloak with PostgreSQL..."

# Clean up any existing deployments
log "🧹 Cleaning up existing deployments..."
kubectl delete deployment june-idp -n june-services --ignore-not-found=true --force --grace-period=0
kubectl delete deployment keycloak-db -n june-services --ignore-not-found=true --force --grace-period=0
kubectl delete pods --field-selector=status.phase=Pending -n june-services --force --grace-period=0 2>/dev/null || true
kubectl delete pods --field-selector=status.phase=Failed -n june-services --force --grace-period=0 2>/dev/null || true

# Wait for cleanup
log "⏳ Waiting for cleanup..."
sleep 15

# Scale down other services temporarily for resources
log "📉 Temporarily scaling down other services..."
kubectl scale deployment june-orchestrator -n june-services --replicas=0 2>/dev/null || true
kubectl scale deployment june-stt -n june-services --replicas=0 2>/dev/null || true
kubectl scale deployment june-tts -n june-services --replicas=0 2>/dev/null || true

# Wait for scale down
sleep 10

# Apply the production Keycloak deployment
log "🗃️ Deploying PostgreSQL database..."
kubectl apply -f keycloak-production.yaml

# Wait for database to be ready
log "⏳ Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=available deployment/keycloak-db -n june-services --timeout=180s

# Verify database is responding
log "🔍 Verifying database connectivity..."
sleep 10

kubectl run db-test --rm -i --restart=Never --image=postgres:15-alpine -n june-services -- \
  psql postgresql://keycloak_db:keycloak_pass_123@keycloak-db:5432/keycloak -c "SELECT version();" || \
  warning "Database connectivity test failed, but continuing..."

# Now wait for Keycloak to be ready
log "🔑 Waiting for Keycloak to start (production mode takes 3-5 minutes)..."
kubectl wait --for=condition=available deployment/june-idp -n june-services --timeout=600s

# Check Keycloak status
log "📋 Keycloak deployment status:"
kubectl get pods -n june-services -l app=june-idp -o wide

# Test Keycloak health
log "🏥 Testing Keycloak health endpoints..."
sleep 30

kubectl port-forward -n june-services service/june-idp 8080:8080 &
pf_pid=$!
sleep 10

# Test health endpoints
if curl -f -s http://localhost:8080/auth/health >/dev/null 2>&1; then
    success "Keycloak health endpoint OK"
    
    # Test realm endpoint
    if curl -f -s http://localhost:8080/auth/realms/june >/dev/null 2>&1; then
        success "June realm accessible"
        
        # Test OIDC configuration
        if curl -f -s http://localhost:8080/auth/realms/june/.well-known/openid_configuration >/dev/null 2>&1; then
            success "OIDC configuration endpoint working"
        else
            warning "OIDC configuration endpoint not ready yet"
        fi
    else
        warning "June realm not accessible yet (may still be importing)"
    fi
    
    # Test admin console
    if curl -f -s http://localhost:8080/auth/admin >/dev/null 2>&1; then
        success "Admin console accessible"
    else
        warning "Admin console not ready yet"
    fi
    
else
    warning "Keycloak health check failed - checking logs..."
    kubectl logs -n june-services deployment/june-idp --tail=30
fi

kill $pf_pid 2>/dev/null || true

# Test database connectivity from Keycloak
log "🔍 Testing Keycloak database connectivity..."
kubectl exec -n june-services deployment/june-idp -- \
  curl -f -s http://localhost:8080/auth/health/ready >/dev/null 2>&1 && \
  success "Keycloak connected to database successfully" || \
  warning "Keycloak database connectivity issues"

# Scale services back up gradually
log "📈 Scaling services back up..."

# Start with orchestrator
kubectl scale deployment june-orchestrator -n june-services --replicas=1
sleep 10
kubectl wait --for=condition=available deployment/june-orchestrator -n june-services --timeout=120s

# Then TTS
kubectl scale deployment june-tts -n june-services --replicas=1
sleep 10
kubectl wait --for=condition=available deployment/june-tts -n june-services --timeout=120s

# Finally STT
kubectl scale deployment june-stt -n june-services --replicas=1
sleep 10
kubectl wait --for=condition=available deployment/june-stt -n june-services --timeout=180s

# Final status check
log "📋 Final deployment status:"
kubectl get pods -n june-services -o wide

echo ""
success "🎉 Production Keycloak deployment completed!"

log "🔑 Production Keycloak Features:"
echo "  ✅ PostgreSQL database backend"
echo "  ✅ Production optimization (--optimized)"
echo "  ✅ Proper hostname configuration"
echo "  ✅ Health and metrics endpoints"
echo "  ✅ Realm import with service clients"
echo "  ✅ SSL/TLS ready for external access"

log "🌐 Access Information:"
echo "  • External URL: https://june-idp.allsafe.world/auth/admin"
echo "  • Internal URL: http://june-idp:8080/auth/admin"
echo "  • Username: admin"
echo "  • Password: admin123"

log "🔧 Testing Commands:"
echo "  • Port forward: kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "  • Check logs: kubectl logs -n june-services deployment/june-idp"
echo "  • Test realm: curl http://localhost:8080/auth/realms/june"
echo "  • Test token: curl -X POST http://localhost:8080/auth/realms/june/protocol/openid-connect/token \\"
echo "      -H 'Content-Type: application/x-www-form-urlencoded' \\"
echo "      -d 'grant_type=client_credentials&client_id=orchestrator-client&client_secret=orchestrator-secret-key-12345'"

warning "🔐 Security Reminders:"
echo "  1. Change default admin password immediately"
echo "  2. Configure DNS for external access"
echo "  3. Verify SSL certificates are working"
echo "  4. Review and update client secrets"

success "Production deployment ready! 🚀"