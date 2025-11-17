#!/bin/bash
# Media Stack - Radarr Installation
set -e
source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN not set"

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Installing Radarr in $NAMESPACE for $DOMAIN"
verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/radarr /mnt/hdd/jellyfin-media/movies
chown -R 1000:1000 /mnt/ssd/media-configs/radarr /mnt/hdd/jellyfin-media/movies

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: radarr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/radarr
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: radarr-config
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
  name: radarr
  namespace: $NAMESPACE
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
        env:
        - {name: PUID, value: "1000"}
        - {name: PGID, value: "1000"}
        - {name: TZ, value: "America/New_York"}
        volumeMounts:
        - {name: config, mountPath: /config}
        - {name: movies, mountPath: /movies}
        - {name: downloads, mountPath: /downloads}
        resources:
          requests: {memory: "128Mi", cpu: "50m"}
          limits: {memory: "512Mi", cpu: "500m"}
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: radarr-config
      - name: movies
        hostPath: {path: /mnt/hdd/jellyfin-media/movies}
      - name: downloads
        hostPath: {path: /mnt/hdd/jellyfin-media/downloads}
---
apiVersion: v1
kind: Service
metadata:
  name: radarr
  namespace: $NAMESPACE
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
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts: [radarr.$DOMAIN]
  rules:
  - host: radarr.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service: {name: radarr, port: {number: 7878}}
EOF

kubectl wait --for=condition=ready pod -l app=radarr -n $NAMESPACE --timeout=300s || warn "Radarr not ready yet"
success "Radarr installed at https://radarr.$DOMAIN"
