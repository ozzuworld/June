#!/bin/bash
# dns-cert-diagnostic.sh - Diagnose DNS and certificate issues
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

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
DOMAIN="allsafe.world"
NAMESPACE="june-services"

echo "🔍 DNS and SSL Certificate Diagnostic"
echo "====================================="
echo ""

# 1. Check static IP
log "1. Checking static IP configuration..."
STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --format="value(address)" 2>/dev/null || echo "NOT_FOUND")
if [ "$STATIC_IP" != "NOT_FOUND" ]; then
    success "Static IP found: $STATIC_IP"
else
    error "Static IP 'june-services-ip' not found"
fi

# 2. Check DNS resolution
log "2. Checking DNS resolution..."
if command -v nslookup >/dev/null 2>&1; then
    DNS_RESULT=$(nslookup $DOMAIN 2>/dev/null || echo "FAILED")
    if [ "$DNS_RESULT" != "FAILED" ]; then
        DNS_IP=$(echo "$DNS_RESULT" | grep -A1 "Name:" | grep "Address:" | awk '{print $2}' | head -1 2>/dev/null || echo "UNKNOWN")
        if [ "$DNS_IP" = "$STATIC_IP" ]; then
            success "DNS correctly points to $STATIC_IP"
        else
            error "DNS points to $DNS_IP, should be $STATIC_IP"
        fi
    else
        error "DNS resolution failed for $DOMAIN"
    fi
else
    warning "nslookup not available, using dig"
    if command -v dig >/dev/null 2>&1; then
        DNS_IP=$(dig +short $DOMAIN | head -1)
        if [ "$DNS_IP" = "$STATIC_IP" ]; then
            success "DNS correctly points to $STATIC_IP"
        else
            error "DNS points to $DNS_IP, should be $STATIC_IP"
        fi
    fi
fi

# 3. Check certificate status
log "3. Checking SSL certificate status..."
CERT_STATUS=$(gcloud compute ssl-certificates describe allsafe-managed --global --format="value(managed.status)" 2>/dev/null || echo "NOT_FOUND")
DOMAIN_STATUS=$(gcloud compute ssl-certificates describe allsafe-managed --global --format="value(managed.domainStatus.allsafe.world)" 2>/dev/null || echo "NOT_FOUND")

echo "Certificate Status: $CERT_STATUS"
echo "Domain Status: $DOMAIN_STATUS"

# 4. Check ingress configuration
log "4. Checking ingress configuration..."
kubectl get ingress -n $NAMESPACE -o wide 2>/dev/null || warning "No ingress found"

# 5. Check load balancer
log "5. Checking load balancer..."
gcloud compute url-maps list --filter="name~june" 2>/dev/null || warning "No URL maps found"
gcloud compute target-https-proxies list --filter="name~june" 2>/dev/null || warning "No HTTPS proxies found"
gcloud compute forwarding-rules list --global --filter="name~june" 2>/dev/null || warning "No forwarding rules found"

# 6. Test connectivity
log "6. Testing connectivity..."
if curl -I --connect-timeout 10 http://$STATIC_IP 2>/dev/null; then
    success "HTTP connectivity to static IP works"
else
    warning "No HTTP response from static IP"
fi

echo ""
echo "🎯 RECOMMENDATIONS:"
echo "==================="

if [ "$DNS_IP" != "$STATIC_IP" ]; then
    echo "🔥 CRITICAL: Fix DNS records first!"
    echo "   Current DNS: $DNS_IP"
    echo "   Required DNS: $STATIC_IP"
    echo ""
    echo "   Add this A record to your DNS provider:"
    echo "   A  $DOMAIN  $STATIC_IP"
    echo ""
fi

if [ "$CERT_STATUS" = "PROVISIONING" ] && [ "$DOMAIN_STATUS" = "FAILED_NOT_VISIBLE" ]; then
    echo "⏳ SSL Certificate waiting for DNS validation"
    echo "   Fix DNS first, then certificate will provision automatically"
    echo ""
fi

echo "🔧 Next steps:"
echo "1. Fix DNS A record: $DOMAIN → $STATIC_IP"
echo "2. Wait 10-15 minutes for DNS propagation"
echo "3. Certificate will auto-provision once DNS is correct"
echo "4. Test: curl https://$DOMAIN/healthz"