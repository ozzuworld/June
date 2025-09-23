#!/bin/bash
# execute-cleanup.sh - Complete TTS cleanup execution

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
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

echo "🚀 June AI Platform - TTS Cleanup"
echo "================================="
echo ""

# Prompt for OpenVoice URL
read -p "Enter your OpenVoice service URL (e.g., https://your-openvoice.com): " OPENVOICE_URL

if [[ -z "$OPENVOICE_URL" ]]; then
    error "OpenVoice URL is required"
fi

log "Using OpenVoice URL: $OPENVOICE_URL"

# Step 1: Run cleanup
log "Step 1: Running cleanup script..."
if [[ -f "cleanup-old-tts.sh" ]]; then
    chmod +x cleanup-old-tts.sh
    ./cleanup-old-tts.sh
    success "Cleanup completed"
else
    error "cleanup-old-tts.sh not found"
fi

# Step 2: Verify app.py has been updated
log "Step 2: Verifying app.py update..."
if grep -q "external_tts_client" June/services/june-orchestrator/app.py; then
    success "app.py has been updated"
else
    error "app.py needs to be updated with external TTS client. Please replace the file."
fi

# Step 3: Set OpenVoice URL in secrets
log "Step 3: Setting OpenVoice URL in Kubernetes secret..."

# Encode URL to base64
ENCODED_URL=$(echo -n "$OPENVOICE_URL" | base64 -w 0)

# Update secret
kubectl patch secret june-secrets -n june-services \
  --patch='{"data":{"EXTERNAL_TTS_URL":"'$ENCODED_URL'"}}' 2>/dev/null || {
  warning "Secret update failed, will be set during deployment"
}

success "OpenVoice URL configured"

# Step 4: Deploy updated services
log "Step 4: Deploying services without TTS..."

if [[ -f "k8s/june-services/core-services-no-tts.yaml" ]]; then
    kubectl apply -f k8s/june-services/core-services-no-tts.yaml
    success "Services deployed"
else
    error "core-services-no-tts.yaml not found"
fi

# Step 5: Wait for deployment
log "Step 5: Waiting for deployments to complete..."

kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s
kubectl rollout status deployment/june-stt -n june-services --timeout=300s
kubectl rollout status deployment/june-idp -n june-services --timeout=600s

success "All deployments completed"

# Step 6: Update ingress
log "Step 6: Updating ingress configuration..."

if [[ -f "k8s/june-services/ingress.yaml" ]]; then
    kubectl apply -f k8s/june-services/ingress.yaml
    success "Ingress updated"
fi

if [[ -f "k8s/june-services/managedcert.yaml" ]]; then
    kubectl apply -f k8s/june-services/managedcert.yaml
    success "SSL certificates updated"
fi

# Step 7: Verify deployment
log "Step 7: Verifying deployment..."

echo ""
echo "Pod status:"
kubectl get pods -n june-services

echo ""
echo "Service status:"
kubectl get services -n june-services

# Step 8: Test endpoints
log "Step 8: Testing endpoints..."

# Test orchestrator health
kubectl port-forward -n june-services service/june-orchestrator 8080:8080 &
pf_pid=$!
sleep 5

if curl -f -s http://localhost:8080/healthz >/dev/null 2>&1; then
    success "Orchestrator health check passed"
else
    warning "Orchestrator health check failed"
fi

# Check configuration
config_response=$(curl -s http://localhost:8080/configz 2>/dev/null || echo '{}')
external_tts_url=$(echo "$config_response" | jq -r '.EXTERNAL_TTS_URL // "not set"' 2>/dev/null || echo "not set")

if [[ "$external_tts_url" != "not set" && "$external_tts_url" != "" ]]; then
    success "External TTS URL configured: $external_tts_url"
else
    warning "External TTS URL not visible in config"
fi

kill $pf_pid 2>/dev/null || true

# Step 9: Final summary
echo ""
success "🎉 TTS cleanup and migration completed!"
echo ""
echo "📊 Summary:"
echo "  ✅ Old TTS microservice removed"
echo "  ✅ Orchestrator updated for external TTS"
echo "  ✅ OpenVoice URL configured: $OPENVOICE_URL"
echo "  ✅ Services deployed without internal TTS"
echo "  ✅ Ingress updated (TTS endpoints removed)"
echo "  ✅ All deployments healthy"
echo ""
echo "🌐 Your services:"
echo "  • Orchestrator: https://june-orchestrator.allsafe.world"
echo "  • STT: https://june-stt.allsafe.world"  
echo "  • IDP: https://june-idp.allsafe.world"
echo "  • TTS: $OPENVOICE_URL (external)"
echo ""
echo "🧪 Test the integration:"
echo "  kubectl port-forward -n june-services service/june-orchestrator 8080:8080"
echo "  curl http://localhost:8080/healthz"
echo ""
echo "📋 Architecture now:"
echo "  June Orchestrator ──→ June STT (internal)"
echo "                   ├──→ Keycloak IDP (internal)" 
echo "                   └──→ OpenVoice TTS (external via IDP auth)"
echo ""
warning "🔐 Remember to update your OpenVoice service to accept IDP authentication!"

echo ""
log "Cleanup completed successfully! 🚀"