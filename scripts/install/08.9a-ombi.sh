#!/bin/bash
# June Platform - Ombi Installation Phase
# Installs Ombi unified request management for Movies, TV Shows, and Music

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

log "Installing Ombi for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create config directory on SSD
log "Creating Ombi config directory on SSD..."
mkdir -p /mnt/ssd/media-configs/ombi
chown -R 1000:1000 /mnt/ssd/media-configs/ombi

log "Creating Ombi persistent volume on SSD..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ombi-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/ombi
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ombi-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 1Gi
EOF

log "Deploying Ombi..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ombi
  namespace: june-services
  labels:
    app: ombi
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ombi
  template:
    metadata:
      labels:
        app: ombi
    spec:
      containers:
      - name: ombi
        image: lscr.io/linuxserver/ombi:latest
        ports:
        - containerPort: 3579
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
            memory: "128Mi"
            cpu: "50m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: ombi-config
---
apiVersion: v1
kind: Service
metadata:
  name: ombi
  namespace: june-services
spec:
  selector:
    app: ombi
  ports:
  - port: 3579
    targetPort: 3579
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ombi-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - ombi.${DOMAIN}
  rules:
  - host: ombi.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: ombi
            port:
              number: 3579
EOF

kubectl wait --for=condition=ready pod -l app=ombi -n june-services --timeout=300s || warn "Ombi not ready yet"

success "Ombi installed successfully!"
echo ""
echo "🎭 Ombi Access:"
echo "  URL: https://ombi.${DOMAIN}"
echo ""
echo "📁 Storage:"
echo "  Config: /mnt/ssd/media-configs/ombi (fast-ssd, on SSD)"
echo ""
echo "⚙️  Configuration:"
echo "  Connections to Jellyfin, Sonarr, Radarr, and Lidarr will be configured"
echo "  automatically by the 08.11-configure-media.sh script"
echo ""
echo "  Ombi supports unified media requests for:"
echo "  - Movies (via Radarr)"
echo "  - TV Shows (via Sonarr)"
echo "  - Music (via Lidarr)"
