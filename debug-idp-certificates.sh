#!/bin/bash
# debug-idp-certificates.sh - Debug IDP access and certificate provisioning

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

echo "🔍 Debugging IDP Access & Certificate Issues"
echo "============================================="

# 1. Check DNS Resolution
echo ""
log "1. Testing DNS Resolution..."
for domain in api.allsafe.world stt.allsafe.world idp.allsafe.world tts.allsafe.world; do
    echo "Testing $domain:"
    if nslookup $domain >/dev/null 2>&1; then
        IP=$(nslookup $domain | grep -A1 "Name:" | tail -1 | awk '{print $2}' 2>/dev/null || echo "unknown")
        if [[ "$IP" == "34.149.245.135" ]]; then
            success "$domain → $IP ✅"
        else
            warning "$domain → $IP (expected 34.149.245.135)"
        fi
    else
        error "$domain - DNS resolution failed"
    fi
done

# 2. Check Cloudflare Proxy Status
echo ""
log "2. Checking if Cloudflare proxy is interfering..."
echo "🔍 Testing direct IP access vs domain access:"

echo ""
echo "Direct IP test (bypasses Cloudflare):"
curl -k -s -o /dev/null -w "Status: %{http_code}, Time: %{time_total}s\n" \
  --connect-timeout 10 \
  http://34.149.245.135 || echo "Direct IP connection failed"

echo ""
echo "Domain tests:"
for domain in api.allsafe.world idp.allsafe.world; do
    echo "Testing $domain:"
    curl -s -o /dev/null -w "HTTP Status: %{http_code}, Time: %{time_total}s\n" \
      --connect-timeout 10 \
      http://$domain || echo "  Failed to connect"
done

# 3. Check Certificate Status in Detail
echo ""
log "3. Detailed Certificate Status..."

echo "ManagedCertificate Status:"
kubectl describe managedcertificate allsafe-certs -n june-services | grep -A 20 "Status:"

echo ""
echo "Certificate Events:"
kubectl describe managedcertificate allsafe-certs -n june-services | grep -A 10 "Events:"

# 4. Check if multiple certificates are conflicting
echo ""
log "4. Checking for certificate conflicts..."
kubectl get managedcertificate -n june-services -o yaml | grep -A 5 -B 5 "domains:"

# 5. Check Keycloak Pod Status
echo ""
log "5. Checking Keycloak/IDP Pod Status..."
kubectl get pods -n june-services | grep -E "(idp|keycloak)"

echo ""
echo "IDP Pod Details:"
IDP_POD=$(kubectl get pods -n june-services | grep -E "(june-idp|keycloak)" | head -1 | awk '{print $1}')
if [[ -n "$IDP_POD" ]]; then
    echo "Pod: $IDP_POD"
    kubectl describe pod $IDP_POD -n june-services | tail -20
    
    echo ""
    echo "Recent IDP logs:"
    kubectl logs $IDP_POD -n june-services --tail=10 2>/dev/null || echo "No logs available"
else
    error "No IDP pod found"
fi

# 6. Test Internal Service Access
echo ""
log "6. Testing Internal Service Access..."
kubectl port-forward -n june-services service/june-idp 8081:8080 &
PF_PID=$!
sleep 3

echo "Testing internal IDP access:"
curl -s -o /dev/null -w "Internal IDP Status: %{http_code}\n" \
  --connect-timeout 5 \
  http://localhost:8081/health 2>/dev/null || echo "Internal IDP connection failed"

kill $PF_PID 2>/dev/null || true

# 7. Check Load Balancer Backend Health
echo ""
log "7. Checking Load Balancer Backend Health..."
kubectl get ingress allsafe-ingress -n june-services -o yaml | grep -A 10 "backends:"

# 8. Cloudflare Configuration Check
echo ""
log "8. Cloudflare Configuration Recommendations..."
echo "🌐 If using Cloudflare, ensure:"
echo "   1. DNS records are set to 'DNS Only' (gray cloud) during certificate provisioning"
echo "   2. SSL/TLS mode is 'Full' or 'Full (strict)'"
echo "   3. No Cloudflare Page Rules blocking Google's validation"

echo ""
warning "📋 Common Certificate Provisioning Issues:"
echo "   • Cloudflare proxy interfering with Google's domain validation"
echo "   • DNS not fully propagated (can take up to 48 hours)"
echo "   • Multiple ManagedCertificate resources causing conflicts"
echo "   • Domain validation challenges failing"

# 9. Certificate Validation Test
echo ""
log "9. Testing Certificate Validation Path..."
echo "Google validates certificates by accessing: http://domain/.well-known/acme-challenge/"
for domain in api.allsafe.world idp.allsafe.world; do
    echo "Testing validation path for $domain:"
    curl -s -o /dev/null -w "Validation path %{url_effective}: Status %{http_code}\n" \
      --connect-timeout 10 \
      http://$domain/.well-known/acme-challenge/test 2>/dev/null || echo "  Validation path unreachable"
done

# 10. Recommendations
echo ""
success "🔧 Immediate Actions to Try:"
echo ""
echo "1. **Cloudflare Settings** (if using Cloudflare):"
echo "   - Set DNS records to 'DNS Only' (gray cloud)"
echo "   - SSL/TLS → Overview → Set to 'Full'"
echo "   - Wait 5-10 minutes, then test again"
echo ""
echo "2. **Clean up duplicate certificates:**
echo "   kubectl delete managedcertificate june-ssl-cert -n june-services"
echo ""
echo "3. **Test direct HTTP access first:**
echo "   curl http://idp.allsafe.world/health"
echo ""
echo "4. **Check certificate progress in 30 minutes:**
echo "   kubectl describe managedcertificate allsafe-certs -n june-services"

echo ""
log "🚀 If certificates are still stuck, we can:"
echo "   • Switch to self-managed certificates temporarily"
echo "   • Use cert-manager with Let's Encrypt"
echo "   • Deploy without HTTPS first, add later"