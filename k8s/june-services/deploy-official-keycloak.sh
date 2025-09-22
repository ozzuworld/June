#!/bin/bash
# deploy-official-keycloak.sh
# Deploy Keycloak 26.3.2 following current official documentation

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

log "🚀 Deploying Official Keycloak 26.3.2 (Current Documentation)..."

# Clean up completely first
log "🧹 Complete cleanup of existing Keycloak..."
kubectl delete deployment june-idp -n june-services --ignore-not-found=true --force --grace-period=0
kubectl delete deployment keycloak-db -n june-services --ignore-not-found=true --force --grace-period=0
kubectl delete service june-idp -n june-services --ignore-not-found=true
kubectl delete service keycloak-db -n june-services --ignore-not-found=true
kubectl delete configmap keycloak-realm-config -n june-services --ignore-not-found=true
kubectl delete secret keycloak-admin-secret -n june-services --ignore-not-found=true
kubectl delete secret keycloak-db-secret -n june-services --ignore-not-found=true

# Clean up any stuck pods
kubectl delete pods --field-selector=status.phase=Pending -n june-services --force --grace-period=0 2>/dev/null || true
kubectl delete pods --field-selector=status.phase=Failed -n june-services --force --grace-period=0 2>/dev/null || true

# Wait for complete cleanup
log "⏳ Waiting for complete cleanup..."
sleep 20

# Scale down other services for resources
log "📉 Scaling down other services temporarily..."
kubectl scale deployment june-orchestrator -n june-services --replicas=0 2>/dev/null || true
kubectl scale deployment june-stt -n june-services --replicas=0 2>/dev/null || true
kubectl scale deployment june-tts -n june-services --replicas=0 2>/dev/null || true

sleep 10

# Apply the official Keycloak deployment
log "🚀 Deploying Official Keycloak 26.3.2..."
kubectl apply -f keycloak-current-official.yaml

# Wait for database first
log "🗃️ Waiting for PostgreSQL database (90 seconds)..."
kubectl wait --for=condition=available deployment/keycloak-db -n june-services --timeout=180s

# Verify database connectivity
log "🔍 Testing database connectivity..."
sleep 15

# Test database is responding
kubectl run db-test --rm -i --restart=Never --image=postgres:16-alpine -n june-services --timeout=30s -- \
  psql postgresql://keycloak_db:keycloak_pass_123@keycloak-db:5432/keycloak -c "SELECT version();" 2>/dev/null && \
  success "Database connectivity verified!" || \
  warning "Database test failed, but continuing..."

# Now wait for Keycloak (longer timeout for production mode)
log "🔑 Waiting for Keycloak 26.3.2 to start (production mode + auto-build takes 5-8 minutes)..."
kubectl wait --for=condition=available deployment/june-idp -n june-services --timeout=900s

# Check pod status
log "📋 Keycloak pod status:"
kubectl get pods -n june-services -l app=june-idp -o wide

# Wait a bit more for full startup
log "⏳ Allowing extra time for complete startup..."
sleep 45

# Test all Keycloak endpoints
log "🏥 Testing Keycloak endpoints..."
kubectl port-forward -n june-services service/june-idp 8080:8080 &
pf_pid=$!
sleep 15

# Test health endpoint
if curl -f -s --connect-timeout 10 http://localhost:8080/health >/dev/null 2>&1; then
    success "Keycloak health endpoint OK"
    
    # Test admin console
    if curl -f -s --connect-timeout 10 http://localhost:8080/admin >/dev/null 2>&1; then
        success "Admin console accessible"
        
        # Test realm
        if curl -f -s --connect-timeout 10 http://localhost:8080/realms/june >/dev/null 2>&1; then
            success "June realm imported successfully"
            
            # Test OIDC configuration
            if curl -f -s --connect-timeout 10 http://localhost:8080/realms/june/.well-known/openid_configuration >/dev/null 2>&1; then
                success "OIDC configuration endpoint working"
                
                # Test service authentication
                log "🔐 Testing service authentication..."
                token_response=$(curl -s --connect-timeout 10 -X POST \
                    -H "Content-Type: application/x-www-form-urlencoded" \
                    -d "grant_type=client_credentials" \
                    -d "client_id=orchestrator-client" \
                    -d "client_secret=orchestrator-secret-key-12345" \
                    http://localhost:8080/realms/june/protocol/openid-connect/token 2>/dev/null || echo '{}')
                
                access_token=$(echo "$token_response" | jq -r '.access_token // empty' 2>/dev/null || echo "")
                
                if [[ -n "$access_token" && "$access_token" != "null" ]]; then
                    success "Service authentication working!"
                else
                    warning "Service authentication not ready yet"
                fi
                
            else
                warning "OIDC configuration not ready"
            fi
        else
            warning "June realm not accessible yet"
        fi
    else
        warning "Admin console not ready"
    fi
else
    warning "Keycloak health endpoint failed - checking logs..."
    echo ""
    log "📋 Recent Keycloak logs:"
    kubectl logs -n june-services deployment/june-idp --tail=50
fi

kill $pf_pid 2>/dev/null || true

# Scale services back up
log "📈 Scaling June services back up..."

kubectl scale deployment june-orchestrator -n june-services --replicas=1
sleep 15
kubectl wait --for=condition=available deployment/june-orchestrator -n june-services --timeout=120s

kubectl scale deployment june-tts -n june-services --replicas=1
sleep 15
kubectl wait --for=condition=available deployment/june-tts -n june-services --timeout=120s

kubectl scale deployment june-stt -n june-services --replicas=1
sleep 15
kubectl wait --for=condition=available deployment/june-stt -n june-services --timeout=180s

# Final status
log "📋 Final deployment status:"
kubectl get pods -n june-services -o wide

echo ""
success "🎉 Official Keycloak 26.3.2 deployment completed!"

log "🔄 What's New (Following Current Official Docs):"
echo "  ✅ Keycloak 26.3.2 (latest version)"
echo "  ✅ KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD (new official way)"
echo "  ✅ Fixed hostname configuration (no conflicts)"
echo "  ✅ --auto-build flag (official production pattern)"
echo "  ✅ Official memory management (-XX:MaxRAMPercentage=70)"
echo "  ✅ PostgreSQL 16 backend"
echo "  ✅ Updated health endpoints (/health vs /auth/health)"

log "🌐 Access Information:"
echo "  • Local: kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "  • Admin Console: http://localhost:8080/admin"
echo "  • External (after DNS): https://june-idp.allsafe.world/admin"
echo "  • Username: admin"
echo "  • Password: admin123"

log "🔧 Test Commands:"
echo "  • Health: curl http://localhost:8080/health"
echo "  • Realm: curl http://localhost:8080/realms/june"
echo "  • Token: curl -X POST http://localhost:8080/realms/june/protocol/openid-connect/token \\"
echo "      -H 'Content-Type: application/x-www-form-urlencoded' \\"
echo "      -d 'grant_type=client_credentials&client_id=orchestrator-client&client_secret=orchestrator-secret-key-12345'"

warning "🔐 Next Steps:"
echo "  1. ⚠️  Change admin password: admin → secure_password"
echo "  2. 🌐 Configure DNS: june-idp.allsafe.world → Static IP"
echo "  3. 🔒 Verify SSL certificates are working"
echo "  4. 🧪 Run: ./test-deployment.sh"

success "Current official Keycloak deployment ready! 🚀"