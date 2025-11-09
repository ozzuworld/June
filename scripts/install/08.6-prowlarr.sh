#!/bin/bash
# June Platform - Prowlarr Installation Phase
# Installs Prowlarr indexer manager

set -e

# Colors
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

# Load configuration
if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    
    CONFIG_FILE="${ROOT_DIR}/config.env"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found: $CONFIG_FILE"
    fi
    
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set. Please check your config.env file."
fi

log "Installing Prowlarr for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create PV for Prowlarr config
log "Creating Prowlarr configuration storage..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: prowlarr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/media/configs/prowlarr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prowlarr-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ""
  resources:
    requests:
      storage: 1Gi
EOF

# Deploy Prowlarr
log "Deploying Prowlarr..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prowlarr
  namespace: june-services
  labels:
    app: prowlarr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prowlarr
  template:
    metadata:
      labels:
        app: prowlarr
    spec:
      containers:
      - name: prowlarr
        image: lscr.io/linuxserver/prowlarr:latest
        ports:
        - containerPort: 9696
          name: http
        env:
        - name: PUID
          value: "1000"
        - name: PGID
          value: "1000"
        - name: TZ
          value: "America/New_York"
        volumeMounts:
        - name: config
          mountPath: /config
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
          claimName: prowlarr-config
---
apiVersion: v1
kind: Service
metadata:
  name: prowlarr
  namespace: june-services
spec:
  selector:
    app: prowlarr
  ports:
  - port: 9696
    targetPort: 9696
    name: http
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prowlarr-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - prowlarr.${DOMAIN}
  rules:
  - host: prowlarr.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: prowlarr
            port:
              number: 9696
EOF

kubectl wait --for=condition=ready pod -l app=prowlarr -n june-services --timeout=300s || warn "Prowlarr not ready yet"

success "Prowlarr installed successfully!"
echo ""
echo "🔍 Prowlarr Access:"
echo "  URL: https://prowlarr.${DOMAIN}"
echo ""
echo "📝 Next Steps:"
echo "  1. Configure indexers (torrent/usenet sites)"
echo "  2. Get API key from Settings > General"
echo "  3. Add to Sonarr and Radarr"
