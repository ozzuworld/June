#!/bin/bash
# fix-dns-alignment.sh - Align ingress with actual DNS records

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }

log "🔧 Aligning ingress with your actual DNS records..."

# Get current ingress IP
INGRESS_IP=$(kubectl get ingress june-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")

if [[ -z "$INGRESS_IP" ]]; then
    warning "Current ingress has no IP, checking static IP..."
    INGRESS_IP="34.149.245.135"  # Your static IP
fi

log "Current ingress IP: $INGRESS_IP"

# 1. Clean up old ingresses with wrong hostnames
log "1. Cleaning up old ingresses..."
kubectl delete ingress test-no-static-ip -n june-services 2>/dev/null || echo "   test-no-static-ip already deleted"
kubectl delete ingress june-ingress -n june-services 2>/dev/null || echo "   june-ingress already deleted"

# Wait for cleanup
sleep 10

# 2. Create corrected ingress with your actual DNS
log "2. Creating ingress with correct DNS records..."

cat > /tmp/allsafe-ingress.yaml << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: allsafe-ingress
  namespace: june-services
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "june-services-ip"
    networking.gke.io/managed-certificates: "allsafe-certs"
spec:
  rules:
  - host: api.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
  - host: stt.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080
  - host: idp.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-idp
            port:
              number: 8080
  - host: tts.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator  # Redirect to orchestrator (external TTS)
            port:
              number: 8080

---
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: allsafe-certs
  namespace: june-services
spec:
  domains:
    - api.allsafe.world
    - stt.allsafe.world
    - idp.allsafe.world
    - tts.allsafe.world
EOF

# Apply the corrected configuration
kubectl apply -f /tmp/allsafe-ingress.yaml
success "Corrected ingress deployed"

# 3. Monitor for IP assignment
log "3. Waiting for IP assignment (this may take 5-10 minutes)..."

for i in {1..20}; do
    sleep 30
    echo ""
    echo "📊 Check $i/20 ($(($i * 30)) seconds):"
    
    CURRENT_IP=$(kubectl get ingress allsafe-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -n "$CURRENT_IP" ]]; then
        success "🎉 Ingress got IP address: $CURRENT_IP"
        INGRESS_IP="$CURRENT_IP"
        break
    else
        echo "⏳ Still waiting for IP assignment..."
        kubectl get ingress allsafe-ingress -n june-services
    fi
    
    if [[ $i -eq 10 ]]; then
        log "Taking longer than expected, but continuing..."
    fi
    
    if [[ $i -eq 20 ]]; then
        warning "Still waiting after 10 minutes. Ingress should eventually get the IP."
        break
    fi
done

# 4. Show final status
echo ""
log "4. Final Configuration Status:"
kubectl get ingress -n june-services
kubectl get managedcertificate -n june-services

# 5. DNS Configuration Instructions
echo ""
success "🌐 Configure these DNS A records:"
echo "   api.allsafe.world → $INGRESS_IP"
echo "   stt.allsafe.world → $INGRESS_IP" 
echo "   idp.allsafe.world → $INGRESS_IP"
echo "   tts.allsafe.world → $INGRESS_IP"

# 6. Testing commands
echo ""
log "🧪 Test commands (after DNS propagation):"
echo "   # Test orchestrator API"
echo "   curl https://api.allsafe.world/healthz"
echo ""
echo "   # Test STT service"
echo "   curl https://stt.allsafe.world/healthz"
echo ""
echo "   # Test Keycloak IDP"
echo "   curl https://idp.allsafe.world/health"
echo ""
echo "   # Test TTS (should redirect to orchestrator)"
echo "   curl https://tts.allsafe.world/healthz"

# 7. Check current service status
echo ""
log "7. Current service status:"
kubectl get pods -n june-services | head -10

# 8. SSL Certificate status
echo ""
log "8. SSL Certificate status:"
kubectl describe managedcertificate allsafe-certs -n june-services | grep -A 10 "Status:"

echo ""
success "🎉 DNS alignment complete!"
echo ""
echo "📋 Next Steps:"
echo "1. Configure DNS A records (see above)"
echo "2. Wait 10-20 minutes for SSL certificates"
echo "3. Test endpoints"
echo "4. Deploy Phase 1 media streaming if needed"

# Cleanup
rm -f /tmp/allsafe-ingress.yaml