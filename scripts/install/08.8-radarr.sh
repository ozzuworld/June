#!/bin/bash
# June Platform - Radarr Installation Phase
# Installs Radarr movie manager with pre-configured authentication

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

log "Installing Radarr for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create config directory on SSD and media folders on HDD
log "Creating Radarr directories..."
mkdir -p /mnt/ssd/media-configs/radarr
mkdir -p /mnt/hdd/jellyfin-media/movies
mkdir -p /mnt/hdd/jellyfin-media/downloads

# Set proper ownership
chown -R 1000:1000 /mnt/ssd/media-configs/radarr
chown -R 1000:1000 /mnt/hdd/jellyfin-media/movies /mnt/hdd/jellyfin-media/downloads

# NOTE: API key will be auto-generated on first start
# Authentication will be configured via API after startup (see 08.11-configure-media.sh)

# Create PV for Radarr config on SSD
log "Creating Radarr persistent volume on SSD..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: radarr-config-pv
spec:
  capacity:
    storage: 2Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/radarr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: radarr-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 2Gi
EOF

# Deploy Radarr
log "Deploying Radarr..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: radarr
  namespace: june-services
  labels:
    app: radarr
spec:
  replicas: 1
  selector:
    matchLabels:
      app: radarr
  template:
    metadata:
      labels:
        app: radarr
    spec:
      containers:
      - name: radarr
        image: lscr.io/linuxserver/radarr:latest
        ports:
        - containerPort: 7878
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
        - name: movies
          mountPath: /movies
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
          claimName: radarr-config
      - name: movies
        hostPath:
          path: /mnt/hdd/jellyfin-media/movies
          type: DirectoryOrCreate
      - name: downloads
        hostPath:
          path: /mnt/hdd/jellyfin-media/downloads
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: radarr
  namespace: june-services
spec:
  selector:
    app: radarr
  ports:
  - port: 7878
    targetPort: 7878
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: radarr-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - radarr.${DOMAIN}
  rules:
  - host: radarr.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: radarr
            port:
              number: 7878
EOF

kubectl wait --for=condition=ready pod -l app=radarr -n june-services --timeout=300s || warn "Radarr not ready yet"

success "Radarr installed successfully!"
echo ""
echo "🎬 Radarr Access:"
echo "  URL: https://radarr.${DOMAIN}"
echo ""
echo "📁 Storage:"
echo "  Config: /mnt/ssd/media-configs/radarr (fast-ssd, on SSD)"
echo "  Movies: /mnt/hdd/jellyfin-media/movies (on HDD)"
echo "  Downloads: /mnt/hdd/jellyfin-media/downloads (on HDD)"
echo ""
echo "⚙️  Configuration:"
echo "  Download client, indexers, and quality profiles will be configured"
echo "  automatically by the 08.11-configure-media.sh script"
