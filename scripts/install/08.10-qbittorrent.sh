#!/bin/bash
# June Platform - qBittorrent Installation Phase
# Installs qBittorrent download client with fixed admin password

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

log "Installing qBittorrent for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Create directories on SSD for config, HDD for downloads
log "Creating directory structure..."
mkdir -p /mnt/ssd/media-configs/qbittorrent/qBittorrent/config
mkdir -p /mnt/hdd/jellyfin-media/downloads/incomplete
mkdir -p /mnt/hdd/jellyfin-media/downloads/complete

# Pre-create qBittorrent config with username, password, and download paths
log "Pre-setting qBittorrent Web UI credentials and download paths..."
cat > /mnt/ssd/media-configs/qbittorrent/qBittorrent.conf <<EOF
[LegalNotice]
Accepted=true

[Preferences]
WebUI\\Username=admin
WebUI\\Password_PBKDF2=@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)
WebUI\\LocalHostAuth=false
Downloads\\SavePath=/downloads/complete
Downloads\\TempPath=/downloads/incomplete
Downloads\\TempPathEnabled=true
Downloads\\PreAllocation=false
Downloads\\UseIncompleteExtension=false
EOF

# Set ownership
chown -R 1000:1000 /mnt/ssd/media-configs/qbittorrent
chown -R 1000:1000 /mnt/hdd/jellyfin-media/downloads

# Create PV for qBittorrent config on SSD
log "Creating qBittorrent persistent volume on SSD..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: qbittorrent-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/qbittorrent
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: qbittorrent-config
  namespace: june-services
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 1Gi
EOF

# Deploy qBittorrent
log "Deploying qBittorrent..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qbittorrent
  namespace: june-services
  labels:
    app: qbittorrent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: qbittorrent
  template:
    metadata:
      labels:
        app: qbittorrent
    spec:
      containers:
      - name: qbittorrent
        image: lscr.io/linuxserver/qbittorrent:latest
        ports:
        - containerPort: 8080
          name: webui
        - containerPort: 6881
          name: tcp
          protocol: TCP
        - containerPort: 6881
          name: udp
          protocol: UDP
        env:
        - name: PUID
          value: "1000"
        - name: PGID
          value: "1000"
        - name: TZ
          value: "America/New_York"
        - name: WEBUI_PORT
          value: "8080"
        volumeMounts:
        - name: config
          mountPath: /config
        - name: downloads
          mountPath: /downloads
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: qbittorrent-config
      - name: downloads
        hostPath:
          path: /mnt/hdd/jellyfin-media/downloads
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: qbittorrent
  namespace: june-services
spec:
  selector:
    app: qbittorrent
  ports:
  - port: 8080
    targetPort: 8080
    name: webui
  - port: 6881
    targetPort: 6881
    name: tcp
    protocol: TCP
  - port: 6881
    targetPort: 6881
    name: udp
    protocol: UDP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qbittorrent-ingress
  namespace: june-services
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: ${WILDCARD_SECRET_NAME}
    hosts:
    - qbittorrent.${DOMAIN}
  rules:
  - host: qbittorrent.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: qbittorrent
            port:
              number: 8080
EOF

kubectl wait --for=condition=ready pod -l app=qbittorrent -n june-services --timeout=300s || warn "qBittorrent not ready yet"

success "qBittorrent installed!"
echo ""
echo "📥 qBittorrent Access:"
echo "  URL: https://qbittorrent.${DOMAIN}"
echo "  Default Username: admin"
echo "  Default Password: adminadmin"
echo ""
echo "📁 Storage:"
echo "  Config: /mnt/ssd/media-configs/qbittorrent (fast-ssd, on SSD)"
echo "  Downloads (container): /downloads/complete & /downloads/incomplete"
echo "  Downloads (host): /mnt/hdd/jellyfin-media/downloads (on HDD)"
echo ""
echo "⚙️  Configuration:"
echo "  qBittorrent will be connected to Sonarr/Radarr automatically"
echo "  by the 08.11-configure-media.sh script"
echo ""
echo "🔗 Connection Details (for manual setup):"
echo "  Host: qbittorrent.june-services.svc.cluster.local"
echo "  Port: 8080"
echo "  Username: admin"
echo "  Password: adminadmin"
echo ""
echo "⚠️  IMPORTANT: Change the default password in Tools > Options > Web UI"
