#!/bin/bash
# june-status-check.sh
# Check current status and guide next steps

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
info() { echo -e "${YELLOW}ℹ️ $1${NC}"; }

NAMESPACE="june-services"
STATIC_IP="34.149.245.135"
DOMAIN="allsafe.world"

echo "🎯 June AI Platform Status Check"
echo "================================"
echo ""

# Check 1: Cluster connectivity
log "1. Checking cluster connectivity..."
if kubectl cluster-info >/dev/null 2>&1; then
    success "Cluster connected"
else
    error "Cluster not accessible"
    exit 1
fi

# Check 2: Namespace exists
log "2. Checking namespace..."
if kubectl get namespace $NAMESPACE >/dev/null 2>&1; then
    success "Namespace exists"
else
    error "Namespace missing"
    exit 1
fi

# Check 3: Pod status
log "3. Checking pod status..."
kubectl get pods -n $NAMESPACE
echo ""

RUNNING_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | grep -c "Running" || echo "0")
TOTAL_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | wc -l)

if [ "$RUNNING_PODS" -eq "$TOTAL_PODS" ] && [ "$TOTAL_PODS" -gt 0 ]; then
    success "All $TOTAL_PODS pods are running"
else
    warning "$RUNNING_PODS/$TOTAL_PODS pods running"
fi

# Check 4: Resource usage
log "4. Checking resource usage..."
if kubectl top pods -n $NAMESPACE >/dev/null 2>&1; then
    kubectl top pods -n $NAMESPACE
    echo ""
    
    # Calculate total CPU usage
    TOTAL_CPU=$(kubectl top pods -n $NAMESPACE --no-headers | awk '{sum += $2} END {print sum}' | sed 's/m//')
    if [ -n "$TOTAL_CPU" ] && [ "$TOTAL_CPU" -gt 0 ]; then
        CPU_PERCENT=$((TOTAL_CPU * 100 / 8000))  # 8000m = 8 cores
        if [ "$CPU_PERCENT" -lt 50 ]; then
            success "CPU usage: ${TOTAL_CPU}m/8000m (${CPU_PERCENT}%) - FREE TIER SAFE"
        else
            warning "CPU usage: ${TOTAL_CPU}m/8000m (${CPU_PERCENT}%) - Monitor closely"
        fi
    fi
else
    warning "Metrics not available (normal for new deployment)"
fi

# Check 5: Services
log "5. Checking services..."
kubectl get svc -n $NAMESPACE
echo ""

# Check 6: Ingress status
log "6. Checking ingress..."
if kubectl get ingress -n $NAMESPACE >/dev/null 2>&1; then
    kubectl get ingress -n $NAMESPACE
    echo ""
    success "Ingress configured"
else
    warning "No ingress found"
fi

# Check 7: DNS resolution
log "7. Checking DNS resolution..."
if nslookup $DOMAIN >/dev/null 2>&1; then
    DNS_IP=$(nslookup $DOMAIN | grep -A1 "Name:" | grep "Address:" | awk '{print $2}' | head -1)
    if [ "$DNS_IP" == "$STATIC_IP" ]; then
        success "DNS correctly points to $STATIC_IP"
        DNS_OK=true
    else
        warning "DNS points to $DNS_IP, should be $STATIC_IP"
        DNS_OK=false
    fi
else
    warning "DNS resolution failed for $DOMAIN"
    DNS_OK=false
fi

# Check 8: SSL Certificate
log "8. Checking SSL certificate..."
if kubectl get managedcertificate -n $NAMESPACE >/dev/null 2>&1; then
    CERT_STATUS=$(kubectl get managedcertificate -n $NAMESPACE -o jsonpath='{.items[0].status.certificateStatus}' 2>/dev/null || echo "Unknown")
    if [ "$CERT_STATUS" == "Active" ]; then
        success "SSL certificate is active"
        SSL_OK=true
    else
        warning "SSL certificate status: $CERT_STATUS"
        SSL_OK=false
    fi
else
    warning "No managed certificate found"
    SSL_OK=false
fi

# Check 9: Service endpoints
log "9. Testing service endpoints..."

# Test with external LB first
LB_IP=$(kubectl get svc june-orchestrator-lb -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")

if [ -n "$LB_IP" ]; then
    info "Testing via LoadBalancer: $LB_IP"
    if curl -s --max-time 10 "http://$LB_IP/v1/healthz" >/dev/null 2>&1; then
        success "Orchestrator accessible via LoadBalancer"
        ORCHESTRATOR_OK=true
    else
        warning "Orchestrator not responding via LoadBalancer"
        ORCHESTRATOR_OK=false
    fi
else
    warning "LoadBalancer IP not found"
    ORCHESTRATOR_OK=false
fi

# Test STT service internally
if kubectl exec deployment/june-orchestrator -n $NAMESPACE -- curl -s --max-time 5 "http://june-stt:8080/healthz" >/dev/null 2>&1; then
    success "STT service accessible internally"
    STT_OK=true
else
    warning "STT service not responding"
    STT_OK=false
fi

# Check 10: TTS Mock (Phase 2)
log "10. Checking TTS mock service..."
if kubectl get deployment june-tts-mock -n $NAMESPACE >/dev/null 2>&1; then
    TTS_REPLICAS=$(kubectl get deployment june-tts-mock -n $NAMESPACE -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "$TTS_REPLICAS" -gt 0 ]; then
        success "TTS mock service deployed and ready"
        TTS_OK=true
    else
        warning "TTS mock service deployed but not ready"
        TTS_OK=false
    fi
else
    info "TTS mock service not deployed (Phase 2 not started)"
    TTS_OK=false
fi

echo ""
echo "📊 STATUS SUMMARY"
echo "=================="

# Overall status
CORE_SERVICES_OK=true
if [ "$ORCHESTRATOR_OK" != "true" ] || [ "$STT_OK" != "true" ]; then
    CORE_SERVICES_OK=false
fi

echo "Core Services: $([ "$CORE_SERVICES_OK" == "true" ] && echo "✅ Ready" || echo "❌ Issues")"
echo "DNS Setup: $([ "$DNS_OK" == "true" ] && echo "✅ Configured" || echo "⚠️ Pending")"
echo "SSL Certificate: $([ "$SSL_OK" == "true" ] && echo "✅ Active" || echo "⚠️ Pending")"
echo "TTS Service: $([ "$TTS_OK" == "true" ] && echo "✅ Phase 2 Complete" || echo "⚠️ Phase 2 Pending")"

echo ""
echo "🎯 NEXT STEPS RECOMMENDATION"
echo "============================"

if [ "$DNS_OK" != "true" ]; then
    echo "🔥 PRIORITY 1: Configure DNS"
    echo "   Add A record: $DOMAIN → $STATIC_IP"
    echo "   Command for your DNS provider:"
    echo "   A  $DOMAIN  $STATIC_IP"
    echo ""
elif [ "$SSL_OK" != "true" ]; then
    echo "⏳ PRIORITY 1: Wait for SSL Certificate"
    echo "   DNS is configured, certificate should provision automatically"
    echo "   Check status: kubectl describe managedcertificate -n $NAMESPACE"
    echo "   Wait 10-15 minutes after DNS propagation"
    echo ""
elif [ "$TTS_OK" != "true" ]; then
    echo "🚀 PRIORITY 1: Deploy Phase 2 (TTS Mock)"
    echo "   Run the TTS deployment command from the guide above"
    echo "   This will complete your audio processing pipeline"
    echo ""
else
    echo "🎉 ALL SYSTEMS OPERATIONAL!"
    echo "   Your June AI Platform is fully deployed and ready"
    echo ""
    echo "🧪 Test your deployment:"
    echo "   curl https://$DOMAIN/v1/healthz"
    echo "   curl https://$DOMAIN/v1/stt/healthz"
    echo "   curl https://$DOMAIN/v1/tts/healthz"
    echo ""
fi

# Show useful commands
echo "🔧 USEFUL COMMANDS"
echo "=================="
echo "Check pods:          kubectl get pods -n $NAMESPACE"
echo "Check resources:     kubectl top pods -n $NAMESPACE"
echo "Check logs:          kubectl logs -f deployment/june-orchestrator -n $NAMESPACE"
echo "Check certificate:   kubectl describe managedcertificate -n $NAMESPACE"
echo "Test LoadBalancer:   curl http://$LB_IP/v1/healthz"

echo ""
echo "📈 FREE TIER STATUS: $([ "$TOTAL_CPU" -lt 4000 ] && echo "EXCELLENT" || echo "MONITOR") (using ${TOTAL_CPU:-0}m/8000m CPU)"
success "Status check complete!"