#!/bin/bash
# fix-cert-ingress.sh - Fix certificate and ingress issues
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

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
DOMAIN="allsafe.world"
NAMESPACE="june-services"

echo "🔧 Certificate and Ingress Fix"
echo "=============================="
echo ""

# Check prerequisites
if ! kubectl cluster-info >/dev/null 2>&1; then
    error "kubectl not configured. Run: gcloud container clusters get-credentials june-unified-cluster --region=us-central1 --project=$PROJECT_ID"
fi

# Step 1: Get current static IP
log "Step 1: Verifying static IP"
STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --format="value(address)" 2>/dev/null || echo "NOT_FOUND")

if [ "$STATIC_IP" = "NOT_FOUND" ]; then
    log "Creating static IP..."
    gcloud compute addresses create june-services-ip --global --project=$PROJECT_ID
    STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --format="value(address)")
fi

success "Static IP: $STATIC_IP"

# Step 2: Check DNS configuration
log "Step 2: Checking DNS configuration"
if command -v nslookup >/dev/null 2>&1; then
    DNS_IP=$(nslookup $DOMAIN 2>/dev/null | grep -A1 "Name:" | grep "Address:" | awk '{print $2}' | head -1 2>/dev/null || echo "UNKNOWN")
elif command -v dig >/dev/null 2>&1; then
    DNS_IP=$(dig +short $DOMAIN | head -1)
else
    DNS_IP="UNKNOWN"
fi

if [ "$DNS_IP" != "$STATIC_IP" ]; then
    warning "DNS Configuration Issue!"
    echo ""
    echo "🔥 CRITICAL: You need to configure your DNS records!"
    echo ""
    echo "Current DNS: $DNS_IP"
    echo "Required IP: $STATIC_IP"
    echo ""
    echo "Add these A records to your DNS provider:"
    echo "A  $DOMAIN                        $STATIC_IP"
    echo "A  api.$DOMAIN                    $STATIC_IP"
    echo "A  june-idp.$DOMAIN               $STATIC_IP"
    echo "A  june-orchestrator.$DOMAIN      $STATIC_IP"
    echo "A  june-stt.$DOMAIN               $STATIC_IP"
    echo ""
    read -p "Press Enter after updating DNS records..." -r
else
    success "DNS correctly configured"
fi

# Step 3: Clean up conflicting ingress configurations
log "Step 3: Cleaning up conflicting ingress configurations"

# Remove old ingresses
kubectl delete ingress --all -n $NAMESPACE --ignore-not-found=true
kubectl delete managedcertificate --all -n $NAMESPACE --ignore-not-found=true

# Remove Kong components (they conflict with GCE ingress)
kubectl delete deployment kong --ignore-not-found=true -n $NAMESPACE
kubectl delete deployment kong-controller --ignore-not-found=true -n $NAMESPACE
kubectl delete deployment kong-gateway --ignore-not-found=true -n $NAMESPACE
kubectl delete service kong-gateway --ignore-not-found=true -n $NAMESPACE

success "Cleaned up old configurations"

# Step 4: Deploy clean ingress configuration
log "Step 4: Deploying clean ingress configuration"

cat <<EOF | kubectl apply -f -
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: allsafe-ssl-cert
  namespace: $NAMESPACE
spec:
  domains:
  - $DOMAIN
  - api.$DOMAIN
  - june-idp.$DOMAIN
  - june-orchestrator.$DOMAIN
  - june-stt.$DOMAIN

---
apiVersion: cloud.google.com/v1
kind: BackendConfig
metadata:
  name: june-backend-config
  namespace: $NAMESPACE
spec:
  healthCheck:
    checkIntervalSec: 15
    timeoutSec: 5
    healthyThreshold: 2
    unhealthyThreshold: 3
    type: HTTP
    requestPath: /healthz
    port: 8080
  timeoutSec: 60
  connectionDraining:
    drainingTimeoutSec: 300

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: june-main-ingress
  namespace: $NAMESPACE
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "june-services-ip"
    networking.gke.io/managed-certificates: "allsafe-ssl-cert"
    networking.gke.io/redirect-to-https: "true"
    cloud.google.com/backend-config: '{"default": "june-backend-config"}'
spec:
  rules:
  - host: $DOMAIN
    http:
      paths:
      - path: /auth
        pathType: Prefix
        backend:
          service:
            name: june-idp
            port:
              number: 8080
      - path: /v1/stt
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
  
  - host: june-idp.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-idp
            port:
              number: 8080

  - host: june-orchestrator.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080

  - host: june-stt.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080

  - host: api.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
EOF

success "New ingress configuration deployed"

# Step 5: Verify services exist
log "Step 5: Verifying services exist"
MISSING_SERVICES=()

for service in june-orchestrator june-stt june-idp; do
    if ! kubectl get service $service -n $NAMESPACE >/dev/null 2>&1; then
        MISSING_SERVICES+=($service)
    fi
done

if [ ${#MISSING_SERVICES[@]} -gt 0 ]; then
    warning "Missing services: ${MISSING_SERVICES[*]}"
    echo ""
    echo "Creating placeholder services..."
    
    for service in "${MISSING_SERVICES[@]}"; do
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: $service
  namespace: $NAMESPACE
spec:
  selector:
    app: $service
  ports:
  - port: 8080
    targetPort: 8080
EOF
    done
fi

# Step 6: Wait for ingress and certificate
log "Step 6: Waiting for ingress and certificate provisioning"

echo "Waiting for ingress to be ready..."
kubectl wait --for=condition=ready ingress june-main-ingress -n $NAMESPACE --timeout=300s || warning "Ingress not ready yet"

echo ""
echo "🔍 CURRENT STATUS:"
echo "=================="

# Show ingress status
echo "Ingress:"
kubectl get ingress -n $NAMESPACE

# Show certificate status
echo ""
echo "Certificate:"
kubectl get managedcertificate -n $NAMESPACE

# Check GCP certificate
echo ""
echo "GCP Certificate Status:"
gcloud compute ssl-certificates describe allsafe-ssl-cert --global --format="table(name,managed.status,managed.domainStatus)" 2>/dev/null || warning "Certificate not found in GCP yet"

echo ""
echo "🎯 NEXT STEPS:"
echo "=============="
echo ""
echo "1. ⏳ Certificate provisioning takes 10-15 minutes"
echo "2. 🔍 Monitor certificate status:"
echo "   kubectl get managedcertificate -n $NAMESPACE"
echo "   gcloud compute ssl-certificates describe allsafe-ssl-cert --global"
echo ""
echo "3. 🧪 Test endpoints once certificate is ACTIVE:"
echo "   curl https://$DOMAIN/healthz"
echo "   curl https://june-stt.$DOMAIN/healthz"
echo "   curl https://june-idp.$DOMAIN/auth"
echo ""
echo "4. 📊 Monitor status:"
echo "   kubectl get pods -n $NAMESPACE"
echo "   kubectl describe ingress june-main-ingress -n $NAMESPACE"
echo ""

if [ "$DNS_IP" != "$STATIC_IP" ]; then
    warning "Remember: DNS must point to $STATIC_IP for certificate to provision!"
fi

success "Fix script completed!"