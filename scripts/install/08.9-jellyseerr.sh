#!/bin/bash
# June Platform - Jellyseerr Installation Phase
# Installs Jellyseerr request management interface

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

log "Installing Jellyseerr for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

log "Creating Jellyseerr storage..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: jellyseerr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/media/configs/jellyseerr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jellyseerr-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ""
  resources:
    requests:
      storage: 1Gi
EOF

log "Deploying Jellyseerr..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jellyseerr
  namespace: june-services
  labels:
    app: jellyseerr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jellyseerr
  template:
    metadata:
      labels:
        app: jellyseerr
    spec:
      containers:
      - name: jellyseerr
        image: fallenbagel/jellyseerr:latest
        ports:
        - containerPort: 5055
          name: http
        env:
        - name: TZ
          value: "America/New_York"
        volumeMounts:
        - name: config
          mountPath: /app/config
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: jellyseerr-config
---
apiVersion: v1
kind: Service
metadata:
  name: jellyseerr
  namespace: june-services
spec:
  selector:
    app: jellyseerr
  ports:
  - port: 5055
    targetPort: 5055
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: jellyseerr-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - requests.${DOMAIN}
  rules:
  - host: requests.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: jellyseerr
            port:
              number: 5055
EOF

kubectl wait --for=condition=ready pod -l app=jellyseerr -n june-services --timeout=300s || warn "Jellyseerr not ready yet"

success "Jellyseerr installed successfully!"
echo ""
echo "🎭 Jellyseerr Access:"
echo "  URL: https://requests.${DOMAIN}"
echo ""
echo "📝 Setup Instructions:"
echo "  1. Navigate to https://requests.${DOMAIN}"
echo "  2. Connect to Jellyfin: https://tv.${DOMAIN}"
echo "  3. Add Sonarr: https://sonarr.${DOMAIN}"
echo "  4. Add Radarr: https://radarr.${DOMAIN}"
echo "  5. Users can now request content!"
