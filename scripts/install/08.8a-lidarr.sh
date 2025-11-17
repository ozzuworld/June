#!/bin/bash
# June Platform - Lidarr Installation Phase
# Installs Lidarr music manager with pre-configured authentication

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

log "Installing Lidarr for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create config directory on SSD and media folders on HDD
log "Creating Lidarr directories..."
mkdir -p /mnt/ssd/media-configs/lidarr
mkdir -p /mnt/hdd/jellyfin-media/music
mkdir -p /mnt/hdd/jellyfin-media/downloads

# Set proper ownership
chown -R 1000:1000 /mnt/ssd/media-configs/lidarr
chown -R 1000:1000 /mnt/hdd/jellyfin-media/music /mnt/hdd/jellyfin-media/downloads

# NOTE: API key will be auto-generated on first start
# Authentication will be configured via API after startup (see 08.11-configure-media.sh)

# Create PV for Lidarr config on SSD
log "Creating Lidarr persistent volume on SSD..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: lidarr-config-pv
spec:
  capacity:
    storage: 2Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/lidarr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: lidarr-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 2Gi
EOF

# Deploy Lidarr
log "Deploying Lidarr..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lidarr
  namespace: june-services
  labels:
    app: lidarr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: lidarr
  template:
    metadata:
      labels:
        app: lidarr
    spec:
      containers:
      - name: lidarr
        image: lscr.io/linuxserver/lidarr:latest
        ports:
        - containerPort: 8686
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
        - name: music
          mountPath: /music
        - name: downloads
          mountPath: /downloads
        resources:
          requests:
            memory: "256Mi"
            cpu: "50m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: lidarr-config
      - name: music
        hostPath:
          path: /mnt/hdd/jellyfin-media/music
          type: DirectoryOrCreate
      - name: downloads
        hostPath:
          path: /mnt/hdd/jellyfin-media/downloads
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: lidarr
  namespace: june-services
spec:
  selector:
    app: lidarr
  ports:
  - port: 8686
    targetPort: 8686
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: lidarr-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - lidarr.${DOMAIN}
  rules:
  - host: lidarr.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: lidarr
            port:
              number: 8686
EOF

kubectl wait --for=condition=ready pod -l app=lidarr -n june-services --timeout=300s || warn "Lidarr not ready yet"

success "Lidarr installed successfully!"
echo ""
echo "🎵 Lidarr Access:"
echo "  URL: https://lidarr.${DOMAIN}"
echo ""
echo "📁 Storage:"
echo "  Config: /mnt/ssd/media-configs/lidarr (fast-ssd, on SSD)"
echo "  Music: /mnt/hdd/jellyfin-media/music (on HDD)"
echo "  Downloads: /mnt/hdd/jellyfin-media/downloads (on HDD)"
echo ""
echo "⚙️  Configuration:"
echo "  Download client, indexers, and quality profiles will be configured"
echo "  automatically by the 08.11-configure-media.sh script"
