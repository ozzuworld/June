#!/bin/bash
# June Platform - Sonarr Installation Phase
# Installs Sonarr TV show manager with pre-configured authentication

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

# Default credentials
MEDIA_STACK_USERNAME="${MEDIA_STACK_USERNAME:-admin}"
MEDIA_STACK_PASSWORD="${MEDIA_STACK_PASSWORD:-Pokemon123!}"

log "Installing Sonarr for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create config directory on SSD and media folders on HDD
log "Creating Sonarr directories..."
mkdir -p /mnt/ssd/media-configs/sonarr
mkdir -p /mnt/hdd/jellyfin-media/tv
mkdir -p /mnt/hdd/jellyfin-media/downloads

# Set proper ownership
chown -R 1000:1000 /mnt/ssd/media-configs/sonarr
chown -R 1000:1000 /mnt/hdd/jellyfin-media/tv /mnt/hdd/jellyfin-media/downloads

# NOTE: API key will be auto-generated on first start
# Authentication will be configured via API after startup (see 08.11-configure-media.sh)

# Create PV for Sonarr config on SSD
log "Creating Sonarr persistent volume on SSD..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: sonarr-config-pv
spec:
  capacity:
    storage: 2Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/sonarr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarr-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 2Gi
EOF

# Deploy Sonarr
log "Deploying Sonarr..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sonarr
  namespace: june-services
  labels:
    app: sonarr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sonarr
  template:
    metadata:
      labels:
        app: sonarr
    spec:
      containers:
      - name: sonarr
        image: lscr.io/linuxserver/sonarr:latest
        ports:
        - containerPort: 8989
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
        - name: tv
          mountPath: /tv
        - name: downloads
          mountPath: /downloads
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: sonarr-config
      - name: tv
        hostPath:
          path: /mnt/hdd/jellyfin-media/tv
          type: DirectoryOrCreate
      - name: downloads
        hostPath:
          path: /mnt/hdd/jellyfin-media/downloads
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: sonarr
  namespace: june-services
spec:
  selector:
    app: sonarr
  ports:
  - port: 8989
    targetPort: 8989
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sonarr-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - sonarr.${DOMAIN}
  rules:
  - host: sonarr.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: sonarr
            port:
              number: 8989
EOF

kubectl wait --for=condition=ready pod -l app=sonarr -n june-services --timeout=300s || warn "Sonarr not ready yet"

success "Sonarr installed successfully!"
echo ""
echo "📺 Sonarr Access:"
echo "  URL: https://sonarr.${DOMAIN}"
echo ""
echo "📁 Storage:"
echo "  Config: /mnt/ssd/media-configs/sonarr (fast-ssd, on SSD)"
echo "  TV Shows: /mnt/hdd/jellyfin-media/tv (on HDD)"
echo "  Downloads: /mnt/hdd/jellyfin-media/downloads (on HDD)"
echo ""
echo "⚙️  Configuration:"
echo "  Download client, indexers, and quality profiles will be configured"
echo "  automatically by the 08.11-configure-media.sh script"
