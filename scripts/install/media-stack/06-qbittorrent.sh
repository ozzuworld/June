#!/bin/bash
# Media Stack - qBittorrent Installation
set -e
source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN not set"

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Installing qBittorrent in $NAMESPACE for $DOMAIN"
verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/qbittorrent
chown -R 1000:1000 /mnt/ssd/media-configs/qbittorrent

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: qbittorrent-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/qbittorrent
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: qbittorrent-config
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
  name: qbittorrent
  namespace: $NAMESPACE
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
        - containerPort: 6881
          protocol: TCP
        - containerPort: 6881
          protocol: UDP
        env:
        - {name: PUID, value: "1000"}
        - {name: PGID, value: "1000"}
        - {name: TZ, value: "America/New_York"}
        - {name: WEBUI_PORT, value: "8080"}
        volumeMounts:
        - {name: config, mountPath: /config}
        - {name: downloads, mountPath: /downloads}
        resources:
          requests: {memory: "256Mi", cpu: "100m"}
          limits: {memory: "1Gi", cpu: "1000m"}
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: qbittorrent-config
      - name: downloads
        hostPath: {path: /mnt/hdd/jellyfin-media/downloads}
---
apiVersion: v1
kind: Service
metadata:
  name: qbittorrent
  namespace: $NAMESPACE
spec:
  selector:
    app: qbittorrent
  ports:
  - name: webui
    port: 8080
    targetPort: 8080
  - name: tcp-bt
    port: 6881
    targetPort: 6881
    protocol: TCP
  - name: udp-bt
    port: 6881
    targetPort: 6881
    protocol: UDP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qbittorrent-ingress
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts: [qbittorrent.$DOMAIN]
  rules:
  - host: qbittorrent.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service: {name: qbittorrent, port: {number: 8080}}
EOF

kubectl wait --for=condition=ready pod -l app=qbittorrent -n $NAMESPACE --timeout=300s || warn "qBittorrent not ready yet"
success "qBittorrent installed at https://qbittorrent.$DOMAIN"
