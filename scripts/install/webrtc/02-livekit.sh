#!/bin/bash
# WebRTC - LiveKit Installation
# Installs LiveKit WebRTC server in media-stack namespace

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

NAMESPACE="media-stack"
LIVEKIT_API_KEY="devkey"
LIVEKIT_API_SECRET="bbUEBtMjPHrvdZwFEwcpPDJkePL5yTrJ"

log "Installing LiveKit in $NAMESPACE namespace..."

verify_namespace "$NAMESPACE"

# Add Helm repo
log "Adding LiveKit Helm repository..."
helm repo add livekit https://helm.livekit.io 2>/dev/null || true
helm repo update

# Get external IP
EXTERNAL_IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')
log "Using external IP: $EXTERNAL_IP"

# Install LiveKit
log "Installing LiveKit server..."
helm upgrade --install livekit livekit/livekit-server \
    --namespace "$NAMESPACE" \
    --set "livekit.keys.$LIVEKIT_API_KEY=$LIVEKIT_API_SECRET" \
    --set server.replicas=1 \
    --set "server.config.rtc.external_ip=$EXTERNAL_IP" \
    --set server.config.rtc.udp_port=7882 \
    --set server.config.rtc.tcp_port=7881 \
    --set server.config.rtc.port_range_start=50000 \
    --set server.config.rtc.port_range_end=60000 \
    --set server.config.rtc.use_external_ip=true \
    --set server.config.rtc.stun_servers='[]' \
    --set "server.config.rtc.turn_servers[0].host=turn.$DOMAIN" \
    --set "server.config.rtc.turn_servers[0].port=3478" \
    --set "server.config.rtc.turn_servers[0].protocol=udp" \
    --set "server.config.rtc.turn_servers[0].username=$TURN_USERNAME" \
    --set "server.config.rtc.turn_servers[0].credential=$STUNNER_PASSWORD" \
    --wait \
    --timeout=15m

wait_for_deployment "livekit-livekit-server" "$NAMESPACE" 300

# Create UDP service for STUNner
log "Creating LiveKit UDP service..."
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: livekit-udp
  namespace: $NAMESPACE
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: livekit-server
  ports:
  - name: udp
    port: 7882
    targetPort: 7882
    protocol: UDP
EOF

# Create ReferenceGrant for cross-namespace access
log "Setting up ReferenceGrant for STUNner access..."
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-media-stack
  namespace: $NAMESPACE
spec:
  from:
  - group: stunner.l7mp.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF

# Update UDPRoute in stunner namespace to point to media-stack
log "Creating UDPRoute for LiveKit..."
kubectl apply -f - <<EOF
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: livekit-udp-route
  namespace: stunner
spec:
  parentRefs:
    - name: stunner-gateway
  rules:
    - backendRefs:
        - name: livekit-udp
          namespace: $NAMESPACE
          port: 7882
EOF

# Create HTTP/HTTPS ingress for LiveKit web interface
log "Creating LiveKit HTTPS ingress..."
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: livekit-ingress
  namespace: $NAMESPACE
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

# Save credentials
mkdir -p "${ROOT_DIR}/config/credentials"
cat > "${ROOT_DIR}/config/credentials/livekit-credentials.yaml" <<EOF
livekit:
  api_key: "$LIVEKIT_API_KEY"
  api_secret: "$LIVEKIT_API_SECRET"
  server_url: "http://livekit-livekit-server.$NAMESPACE.svc.cluster.local"
EOF

success "LiveKit installed successfully in $NAMESPACE namespace"
echo ""
echo "🎮 LiveKit Server:"
echo "   Web URL: https://livekit.$DOMAIN"
echo "   Internal URL: http://livekit-livekit-server.$NAMESPACE.svc.cluster.local"
echo "   API Key: $LIVEKIT_API_KEY"
echo "   Namespace: $NAMESPACE"
echo ""
echo "🔗 Connected to TURN: turn.$DOMAIN:3478"
echo ""
echo "🔍 Verify ingress:"
echo "   kubectl get ingress livekit-ingress -n $NAMESPACE"
