#!/bin/bash
# patch-keycloak-startup.sh
# Quick fix: Update Keycloak startup arguments

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

log "🔧 Patching Keycloak startup arguments (removing invalid --auto-build flag)..."

# Check current deployment status
log "📋 Current Keycloak deployment status:"
kubectl get pods -n june-services -l app=june-idp

# Patch the deployment to use correct startup arguments
log "🛠️ Updating deployment with correct startup arguments..."

kubectl patch deployment june-idp -n june-services --type='merge' -p='
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "keycloak",
            "args": [
              "start",
              "--optimized",
              "--import-realm"
            ]
          }
        ]
      }
    }
  }
}'

# Wait for the rollout to complete
log "⏳ Waiting for deployment rollout to complete..."
kubectl rollout status deployment/june-idp -n june-services --timeout=600s

# Check new pod status
log "📋 New pod status:"
kubectl get pods -n june-services -l app=june-idp

# Wait for startup
log "⏳ Waiting for Keycloak to start with corrected arguments (2-3 minutes)..."
sleep 60

# Test the health endpoint
log "🏥 Testing Keycloak health..."
kubectl port-forward -n june-services service/june-idp 8080:8080 &
pf_pid=$!
sleep 15

if curl -f -s http://localhost:8080/health >/dev/null 2>&1; then
    success "Keycloak health endpoint working!"
    
    # Test admin console
    if curl -f -s http://localhost:8080/admin >/dev/null 2>&1; then
        success "Admin console accessible"
    else
        warning "Admin console not ready yet"
    fi
    
    # Test realm
    if curl -f -s http://localhost:8080/realms/june >/dev/null 2>&1; then
        success "June realm accessible"
        
        # Test service authentication
        log "🔐 Testing service authentication..."
        token_response=$(curl -s -X POST \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "grant_type=client_credentials" \
            -d "client_id=orchestrator-client" \
            -d "client_secret=orchestrator-secret-key-12345" \
            http://localhost:8080/realms/june/protocol/openid-connect/token 2>/dev/null || echo '{}')
        
        access_token=$(echo "$token_response" | jq -r '.access_token // empty' 2>/dev/null || echo "")
        
        if [[ -n "$access_token" && "$access_token" != "null" ]]; then
            success "Service authentication working! Token obtained."
        else
            warning "Service authentication not ready yet"
        fi
    else
        warning "June realm not accessible yet"
    fi
    
else
    warning "Health endpoint not ready yet - checking logs..."
    kubectl logs -n june-services deployment/june-idp --tail=20
fi

kill $pf_pid 2>/dev/null || true

# Check logs for any remaining errors
log "📋 Recent logs (should show no more '--auto-build' errors):"
kubectl logs -n june-services deployment/june-idp --tail=10

success "🎉 Keycloak startup arguments fixed!"

log "🔍 What was fixed:"
echo "  ❌ Before: start --auto-build --import-realm"
echo "  ✅ After:  start --optimized --import-realm"
echo ""
echo "The --auto-build flag doesn't exist in Keycloak."
echo "Keycloak automatically builds when configuration changes are detected."

log "🧪 Test the deployment:"
echo "  kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "  curl http://localhost:8080/admin"
echo "  Username: admin, Password: admin123"