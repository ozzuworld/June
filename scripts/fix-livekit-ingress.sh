#!/bin/bash
# Quick fix to create LiveKit ingress in media-stack namespace

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Load config
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
else
    error "config.env not found"
fi

log "Fixing LiveKit ingress in media-stack namespace..."

# Delete old ingress if it exists in wrong namespace
if kubectl get ingress livekit-ingress -n media &>/dev/null; then
    log "Removing old ingress from 'media' namespace..."
    kubectl delete ingress livekit-ingress -n media
fi

if kubectl get ingress livekit-ingress -n june-services &>/dev/null; then
    log "Removing old ingress from 'june-services' namespace..."
    kubectl delete ingress livekit-ingress -n june-services
fi

# Verify certificate exists
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
if ! kubectl get secret "$WILDCARD_SECRET_NAME" -n media-stack &>/dev/null; then
    log "Certificate not found, syncing from june-services..."
    kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services -o yaml | \
        sed "s/namespace: june-services/namespace: media-stack/" | \
        kubectl apply -f -
fi

# Create new ingress in media-stack namespace
log "Creating LiveKit ingress in media-stack namespace..."
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: livekit-ingress
  namespace: media-stack
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "86400"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "86400"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/server-snippets: |
      client_body_buffer_size 10M;
      client_max_body_size 10M;
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - livekit.$DOMAIN
    secretName: $WILDCARD_SECRET_NAME
  rules:
  - host: livekit.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: livekit-livekit-server
            port:
              number: 80
EOF

success "LiveKit ingress created!"
echo ""
echo "🎮 LiveKit is now accessible at: https://livekit.$DOMAIN"
echo ""
echo "🔍 Verify:"
echo "   kubectl get ingress livekit-ingress -n media-stack"
echo "   kubectl get pods -n media-stack | grep livekit"
echo ""
