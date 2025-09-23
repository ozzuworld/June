#!/bin/bash
# troubleshoot-ingress.sh - Complete GKE ingress troubleshooting

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

PROJECT_ID="main-buffer-469817-v7"
REGION="us-central1"
CLUSTER_NAME="june-unified-cluster"

log "🔍 Starting comprehensive GKE ingress troubleshooting..."

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 1: Check Cluster Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check HTTP Load Balancing addon
log "Checking HTTP Load Balancing addon..."
if kubectl get deployment ingress-gce-controller -n kube-system >/dev/null 2>&1; then
    success "HTTP Load Balancing addon is enabled"
else
    warning "HTTP Load Balancing addon may be disabled"
    echo "To enable: gcloud container clusters update $CLUSTER_NAME --update-addons=HttpLoadBalancing=ENABLED --region=$REGION"
fi

# Check cluster type
log "Checking cluster configuration..."
gcloud container clusters describe june-unified-cluster --region=$REGION --format="value(autopilot.enabled,network,subnetwork)" | while read autopilot network subnetwork; do
    echo "Autopilot: $autopilot"
    echo "Network: $network"
    echo "Subnetwork: $subnetwork"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 2: Check Static IP Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check static IP
log "Checking static IP addresses..."
STATIC_IPS=$(gcloud compute addresses list --global --format="table(name,address,status)" --filter="name:(june-services-ip OR allsafe-gclb-ip)")
echo "$STATIC_IPS"

if echo "$STATIC_IPS" | grep -q "june-services-ip"; then
    success "Static IP 'june-services-ip' exists"
else
    warning "Creating static IP 'june-services-ip'..."
    gcloud compute addresses create june-services-ip --global --project=$PROJECT_ID
    success "Static IP created"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 3: Check Services Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check services exist and have correct annotations
log "Checking services in june-services namespace..."
kubectl get services -n june-services

echo ""
log "Checking service NEG annotations..."
SERVICES=(june-orchestrator june-stt june-idp)
for service in "${SERVICES[@]}"; do
    if kubectl get service $service -n june-services >/dev/null 2>&1; then
        NEG_ANNOTATION=$(kubectl get service $service -n june-services -o jsonpath='{.metadata.annotations.cloud\.google\.com/neg}' 2>/dev/null || echo "MISSING")
        if [[ "$NEG_ANNOTATION" == *'"ingress": true'* ]]; then
            success "$service has correct NEG annotation"
        else
            warning "$service missing NEG annotation, adding it..."
            kubectl annotate service $service -n june-services \
              cloud.google.com/neg='{"ingress": true}' --overwrite
            success "$service NEG annotation added"
        fi
    else
        error "$service not found"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 4: Check Current Ingress Issues"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check existing ingresses
log "Current ingress status..."
kubectl get ingress -n june-services

echo ""
log "Detailed ingress description..."
kubectl get ingress -n june-services -o name | while read ingress; do
    echo "━━━ $ingress ━━━"
    kubectl describe "$ingress" -n june-services | tail -20
    echo ""
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 5: Check Resource Quotas"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check quotas
log "Checking GCP quotas..."
echo "Backends quota:"
gcloud compute project-info describe --format="table(quotas.metric,quotas.usage,quotas.limit)" --filter="quotas.metric:BACKEND_SERVICES"
echo ""
echo "Forwarding rules quota:"
gcloud compute project-info describe --format="table(quotas.metric,quotas.usage,quotas.limit)" --filter="quotas.metric:FORWARDING_RULES"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 6: Fix and Redeploy Ingress"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Delete broken ingress
log "Cleaning up existing ingresses..."
kubectl delete ingress test-no-static-ip -n june-services 2>/dev/null || true
kubectl delete ingress allsafe-ingress -n june-services 2>/dev/null || true

# Wait for cleanup
log "Waiting for cleanup..."
sleep 10

# Create working ingress
log "Creating working ingress configuration..."
cat > /tmp/working-ingress.yaml << EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: june-ingress
  namespace: june-services
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "june-services-ip"
    networking.gke.io/managed-certificates: "june-ssl-cert"
spec:
  rules:
  - host: june-orchestrator.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
  - host: june-stt.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080
  - host: june-idp.allsafe.world
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
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: june-ssl-cert
  namespace: june-services
spec:
  domains:
    - june-orchestrator.allsafe.world
    - june-stt.allsafe.world
    - june-idp.allsafe.world
EOF

# Apply working ingress
kubectl apply -f /tmp/working-ingress.yaml
success "Working ingress deployed"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 STEP 7: Monitor Progress"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

log "Monitoring ingress creation (this takes 5-10 minutes)..."

for i in {1..20}; do
    sleep 30
    echo ""
    echo "📊 Check $i/20 ($(($i * 30)) seconds):"
    
    INGRESS_IP=$(kubectl get ingress june-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -n "$INGRESS_IP" ]]; then
        success "🎉 Ingress got IP address: $INGRESS_IP"
        break
    else
        echo "⏳ Still waiting for IP address..."
        kubectl get ingress june-ingress -n june-services
        
        # Show events for debugging
        echo ""
        echo "Recent events:"
        kubectl get events -n june-services --sort-by=.lastTimestamp | tail -5
    fi
    
    if [[ $i -eq 20 ]]; then
        error "Ingress still has no IP after 10 minutes. Check errors above."
        kubectl describe ingress june-ingress -n june-services
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 FINAL STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

kubectl get ingress -n june-services
kubectl get managedcertificate -n june-services

FINAL_IP=$(kubectl get ingress june-ingress -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "NONE")

if [[ "$FINAL_IP" != "NONE" ]]; then
    success "🎉 SUCCESS! Ingress is working with IP: $FINAL_IP"
    echo ""
    echo "🌐 Configure DNS:"
    echo "  june-orchestrator.allsafe.world → $FINAL_IP"
    echo "  june-stt.allsafe.world → $FINAL_IP"
    echo "  june-idp.allsafe.world → $FINAL_IP"
    echo ""
    echo "🔐 SSL certificates will auto-provision in 10-20 minutes"
else
    error "❌ Ingress still has no IP. Check the events and logs above."
fi

# Cleanup
rm -f /tmp/working-ingress.yaml