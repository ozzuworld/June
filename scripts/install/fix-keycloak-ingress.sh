#!/bin/bash
# Fix script for Keycloak Operator ingress issues
# Common problem: The operator-managed ingress doesn't work properly with Traefik

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

ROOT_DIR="$1"

if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    CONFIG_FILE="${ROOT_DIR}/config.env"
    [ ! -f "$CONFIG_FILE" ] && error "Configuration file not found: $CONFIG_FILE"
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set."

NAMESPACE="june-services"
KEYCLOAK_HOSTNAME="idp.${DOMAIN}"

log "Fixing Keycloak ingress for domain: $DOMAIN"

# Step 1: Find the actual service name created by Keycloak Operator
log "Step 1: Discovering Keycloak service..."

SERVICE_NAME=$(kubectl get svc -n $NAMESPACE -o name | grep keycloak | head -1 | cut -d'/' -f2)

if [ -z "$SERVICE_NAME" ]; then
    error "No Keycloak service found in namespace $NAMESPACE"
fi

log "Found service: $SERVICE_NAME"

# Get service details
SERVICE_PORT=$(kubectl get svc $SERVICE_NAME -n $NAMESPACE -o jsonpath='{.spec.ports[0].port}')
log "Service port: $SERVICE_PORT"

success "Service discovered: $SERVICE_NAME:$SERVICE_PORT"

# Step 2: Check if operator-managed ingress exists and delete it if problematic
log "Step 2: Checking existing ingress..."

EXISTING_INGRESS=$(kubectl get ingress -n $NAMESPACE -o name | grep keycloak || echo "")

if [ -n "$EXISTING_INGRESS" ]; then
    warn "Found existing Keycloak ingress: $EXISTING_INGRESS"
    log "Deleting operator-managed ingress to recreate manually..."
    kubectl delete $EXISTING_INGRESS -n $NAMESPACE
    success "Deleted existing ingress"
fi

# Step 3: Disable ingress in Keycloak CR
log "Step 3: Disabling operator-managed ingress..."

kubectl patch keycloak keycloak -n $NAMESPACE --type='json' \
    -p='[{"op": "remove", "path": "/spec/ingress"}]' || \
    warn "Could not remove ingress from CR (might not exist)"

# Step 4: Create manual ingress with correct service backend
log "Step 4: Creating manual ingress with correct backend..."

cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak-ingress
  namespace: $NAMESPACE
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - $KEYCLOAK_HOSTNAME
      secretName: keycloak-tls
  rules:
    - host: $KEYCLOAK_HOSTNAME
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: $SERVICE_NAME
                port:
                  number: $SERVICE_PORT
EOF

success "Manual ingress created"

# Step 5: Verify ingress is working
log "Step 5: Verifying ingress configuration..."

sleep 5

kubectl get ingress keycloak-ingress -n $NAMESPACE

# Step 6: Test connectivity
log "Step 6: Testing Keycloak connectivity..."

log "Waiting 10 seconds for ingress to propagate..."
sleep 10

log "Testing health endpoint..."
if curl -k -s -f "https://$KEYCLOAK_HOSTNAME/health" > /dev/null 2>&1; then
    success "Keycloak is now accessible!"
else
    warn "Keycloak might still be initializing. Check logs with:"
    echo "  kubectl logs -n $NAMESPACE -l app=keycloak"
    echo "  kubectl describe ingress keycloak-ingress -n $NAMESPACE"
fi

echo ""
success "Keycloak ingress fix completed!"
echo ""
echo "Keycloak URL: https://$KEYCLOAK_HOSTNAME"
echo "Admin Console: https://$KEYCLOAK_HOSTNAME/admin"
echo ""
