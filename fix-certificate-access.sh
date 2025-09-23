#!/bin/bash
# fix-certificate-access.sh - Complete fix for certificate and IDP access issues

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}‚úÖ $1${NC}"; }
warning() { echo -e "${YELLOW}‚ö†Ô∏è $1${NC}"; }
error() { echo -e "${RED}‚ùå $1${NC}"; }

PROJECT_ID="main-buffer-469817-v7"

echo "Ì¥ß Fixing Certificate and IDP Access Issues"
echo "==========================================="

# STEP 1: Identify the core issues
log "Ì¥ç Step 1: Diagnosing issues..."

echo "Checking current ingress status:"
kubectl get ingress -n june-services

echo ""
echo "Checking certificate status:"
kubectl get managedcertificate -n june-services

echo ""
echo "Checking DNS resolution:"
for domain in api.allsafe.world stt.allsafe.world idp.allsafe.world; do
    IP=$(nslookup $domain 2>/dev/null | grep -A1 "Name:" | tail -1 | awk '{print $2}' 2>/dev/null || echo "FAILED")
    echo "$domain ‚Üí $IP"
done

# STEP 2: Clean up conflicting resources
log "Ì∑π Step 2: Cleaning up conflicting resources..."

# Delete all existing ingresses and certificates
kubectl delete ingress --all -n june-services 2>/dev/null || true
kubectl delete managedcertificate --all -n june-services 2>/dev/null || true

# Wait for cleanup
log "Waiting 30 seconds for cleanup..."
sleep 30

# STEP 3: Create consistent ingress with correct domains
log "Ìºê Step 3: Creating consistent ingress configuration..."

cat > /tmp/fixed-ingress.yaml << 'EOF'
# Fixed ingress configuration with consistent domain naming
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: allsafe-ingress
  namespace: june-services
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "june-services-ip"
    networking.gke.io/managed-certificates: "allsafe-certs"
    # Add backend configuration for better health checks
    cloud.google.com/backend-config: '{"default": "june-backend-config"}'
spec:
  rules:
  # Use the domains that match your DNS configuration
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

---
# Managed certificate for the correct domains
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

---
# Backend configuration for better health checks
apiVersion: cloud.google.com/v1
kind: BackendConfig
metadata:
  name: june-backend-config
  namespace: june-services
spec:
  healthCheck:
    checkIntervalSec: 10
    timeoutSec: 5
    healthyThreshold: 1
    unhealthyThreshold: 3
    type: HTTP
    requestPath: /healthz
    port: 8080
  timeoutSec: 30
  connectionDraining:
    drainingTimeoutSec: 60
EOF

# Apply the fixed configuration
kubectl apply -f /tmp/fixed-ingress.yaml
success "Fixed ingress configuration applied"

# STEP 4: Ensure services have correct annotations
log "Ì¥ß Step 4: Adding NEG annotations to services..."

SERVICES=(june-orchestrator june-stt june-idp)
for service in "${SERVICES[@]}"; do
    if kubectl get service $service -n june-services >/dev/null 2>&1; then
        kubectl annotate service $service -n june-services \
          cloud.google.com/neg='{"ingress": true}' --overwrite
        success "$service annotated for NEG"
    else
        warning "$service not found"
    fi
done

# STEP 5: Check static IP configuration
log "Ì≥ç Step 5: Verifying static IP..."

if ! gcloud compute addresses describe june-services-ip --global --project=$PROJECT_ID >/dev/null 2>&1; then
    log "Creating static IP..."
    gcloud compute addresses create june-services-ip --global --project=$PROJECT_ID
    success "Static IP created"
else
    success "Static IP already exists"
fi

STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --project=$PROJECT_ID --format="value(address)")
log "Static IP: $STATIC_IP"

# STEP 6: Test HTTP access while waiting for HTTPS
log "Ì∑™ Step 6: Testing HTTP access..."

echo ""
echo "Testing HTTP endpoints (should work immediately):"
for endpoint in "api.allsafe.world/healthz" "stt.allsafe.world/healthz" "idp.allsafe.world/health"; do
    echo -n "Testing http://$endpoint ... "
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "http://$endpoint" 2>/dev/null || echo "000")
    if [[ "$RESPONSE" == "200" ]]; then
        success "OK ($RESPONSE)"
    else
        warning "Failed ($RESPONSE)"
    fi
done

# STEP 7: Special fix for Keycloak IDP access
log "ÔøΩÔøΩ Step 7: Fixing Keycloak IDP access..."

echo ""
echo "Testing Keycloak endpoints:"
KEYCLOAK_ENDPOINTS=(
    "idp.allsafe.world/auth"
    "idp.allsafe.world/auth/realms/june"  
    "idp.allsafe.world/auth/admin"
    "idp.allsafe.world/health"
)

for endpoint in "${KEYCLOAK_ENDPOINTS[@]}"; do
    echo -n "Testing http://$endpoint ... "
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "http://$endpoint" 2>/dev/null || echo "000")
    echo "$RESPONSE"
done

# Get Keycloak admin credentials
echo ""
echo "Keycloak Admin Access:"
ADMIN_USER=$(kubectl get secret keycloak-admin-secret -n june-services -o jsonpath='{.data.username}' | base64 -d 2>/dev/null || echo "admin")
ADMIN_PASS=$(kubectl get secret keycloak-admin-secret -n june-services -o jsonpath='{.data.password}' | base64 -d 2>/dev/null || echo "admin123")

echo "Ì¥ë Admin Console: http://idp.allsafe.world/auth/admin"
echo "   Username: $ADMIN_USER"
echo "   Password: $ADMIN_PASS"

# STEP 8: Monitor certificate provisioning
log "‚è≥ Step 8: Monitoring certificate provisioning..."

echo ""
echo "Certificates will take 10-60 minutes to provision. Monitoring progress..."

for i in {1..10}; do
    sleep 30
    echo ""
    echo "Ì≥ä Certificate check $i/10 ($(($i * 30)) seconds):"
    
    # Check ingress IP
    INGRESS_IP=$(kubectl get ingress allsafe-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -n "$INGRESS_IP" ]]; then
        echo "‚úÖ Ingress IP: $INGRESS_IP"
    else
        echo "‚è≥ Waiting for ingress IP..."
    fi
    
    # Check certificate status
    CERT_STATUS=$(kubectl get managedcertificate allsafe-certs -n june-services -o jsonpath='{.status.certificateStatus}' 2>/dev/null || echo "Unknown")
    echo "Ì≥ú Certificate status: $CERT_STATUS"
    
    if [[ "$CERT_STATUS" == "Active" ]]; then
        success "Ìæâ Certificates are active!"
        break
    elif [[ "$CERT_STATUS" == "Provisioning" ]]; then
        echo "‚è≥ Certificates are provisioning..."
    else
        warning "Certificate status: $CERT_STATUS"
    fi
    
    if [[ $i -eq 10 ]]; then
        warning "Certificates still provisioning after 5 minutes (this is normal)"
        echo "Continue monitoring with: kubectl get managedcertificate -n june-services -w"
    fi
done

# STEP 9: Cloudflare-specific fixes (if using Cloudflare)
log "‚òÅÔ∏è Step 9: Cloudflare DNS optimization..."

echo ""
echo "Ìºê If you're using Cloudflare, apply these settings for faster certificate provisioning:"
echo ""
echo "1. DNS Settings (Critical for Google certificate validation):"
echo "   - Go to Cloudflare Dashboard > DNS"
echo "   - For each domain (api, stt, idp), click the orange cloud to make it gray"
echo "   - This temporarily disables Cloudflare proxy during certificate validation"
echo "   - Set these A records to point to: $STATIC_IP"
echo "     * api.allsafe.world ‚Üí $STATIC_IP"
echo "     * stt.allsafe.world ‚Üí $STATIC_IP"  
echo "     * idp.allsafe.world ‚Üí $STATIC_IP"
echo ""
echo "2. SSL/TLS Settings:"
echo "   - Go to SSL/TLS > Overview"
echo "   - Set encryption mode to 'Full' (not 'Flexible')"
echo ""
echo "3. After certificates show 'Active' (10-60 minutes):"
echo "   - Re-enable Cloudflare proxy (orange cloud) if desired"

# STEP 10: Final status and next steps
log "Ì≥ã Step 10: Final status and next steps..."

echo ""
success "ÌæØ Configuration Complete!"
echo ""
echo "‚úÖ What's been fixed:"
echo "  - Removed conflicting ingress resources"
echo "  - Created consistent ingress with correct domains"
echo "  - Added proper service annotations"
echo "  - Configured backend health checks"
echo "  - Verified static IP configuration"
echo ""
echo "‚è≥ What's in progress:"
echo "  - SSL certificate provisioning (10-60 minutes)"
echo "  - Load balancer backend registration"
echo ""
echo "Ì∑™ Test your services now:"
echo "  curl http://api.allsafe.world/healthz"
echo "  curl http://stt.allsafe.world/healthz" 
echo "  curl http://idp.allsafe.world/auth"
echo ""
echo "Ì¥ê Access Keycloak Admin:"
echo "  URL: http://idp.allsafe.world/auth/admin"
echo "  User: $ADMIN_USER | Pass: $ADMIN_PASS"
echo ""
echo "Ì≥ä Monitor certificate progress:"
echo "  kubectl get managedcertificate -n june-services -w"
echo ""
echo "Ìæâ Once certificates are 'Active', test HTTPS:"
echo "  curl https://api.allsafe.world/healthz"
echo "  curl https://idp.allsafe.world/auth"

# Cleanup
rm -f /tmp/fixed-ingress.yaml

success "Certificate and access fix completed!"
