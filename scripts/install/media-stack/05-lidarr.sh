#!/bin/bash
# Media Stack - Lidarr Installation
set -e
source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN not set"

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Installing Lidarr in $NAMESPACE for $DOMAIN"
verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/lidarr /mnt/hdd/jellyfin-media/music
chown -R 1000:1000 /mnt/ssd/media-configs/lidarr /mnt/hdd/jellyfin-media/music

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: lidarr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/lidarr
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: lidarr-config
  namespace: $NAMESPACE
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lidarr
  namespace: $NAMESPACE
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
        env:
        - {name: PUID, value: "1000"}
        - {name: PGID, value: "1000"}
        - {name: TZ, value: "America/New_York"}
        volumeMounts:
        - {name: config, mountPath: /config}
        - {name: music, mountPath: /music}
        - {name: downloads, mountPath: /downloads}
        resources:
          requests: {memory: "128Mi", cpu: "50m"}
          limits: {memory: "512Mi", cpu: "500m"}
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: lidarr-config
      - name: music
        hostPath: {path: /mnt/hdd/jellyfin-media/music}
      - name: downloads
        hostPath: {path: /mnt/hdd/jellyfin-media/downloads}
---
apiVersion: v1
kind: Service
metadata:
  name: lidarr
  namespace: $NAMESPACE
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
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts: [lidarr.$DOMAIN]
  rules:
  - host: lidarr.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service: {name: lidarr, port: {number: 8686}}
EOF

kubectl wait --for=condition=ready pod -l app=lidarr -n $NAMESPACE --timeout=300s || warn "Lidarr not ready yet"
success "Lidarr installed at https://lidarr.$DOMAIN"
