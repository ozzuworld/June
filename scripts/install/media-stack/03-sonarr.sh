#!/bin/bash
# Media Stack - Sonarr Installation
set -e
source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN not set"

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Installing Sonarr in $NAMESPACE for $DOMAIN"
verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/sonarr /mnt/hdd/jellyfin-media/tv
chown -R 1000:1000 /mnt/ssd/media-configs/sonarr /mnt/hdd/jellyfin-media/tv

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: sonarr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/sonarr
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarr-config
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
  name: sonarr
  namespace: $NAMESPACE
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
        env:
        - {name: PUID, value: "1000"}
        - {name: PGID, value: "1000"}
        - {name: TZ, value: "America/New_York"}
        volumeMounts:
        - {name: config, mountPath: /config}
        - {name: tv, mountPath: /tv}
        - {name: downloads, mountPath: /downloads}
        resources:
          requests: {memory: "128Mi", cpu: "50m"}
          limits: {memory: "512Mi", cpu: "500m"}
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: sonarr-config
      - name: tv
        hostPath: {path: /mnt/hdd/jellyfin-media/tv}
      - name: downloads
        hostPath: {path: /mnt/hdd/jellyfin-media/downloads}
---
apiVersion: v1
kind: Service
metadata:
  name: sonarr
  namespace: $NAMESPACE
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
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts: [sonarr.$DOMAIN]
  rules:
  - host: sonarr.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service: {name: sonarr, port: {number: 8989}}
EOF

kubectl wait --for=condition=ready pod -l app=sonarr -n $NAMESPACE --timeout=300s || warn "Sonarr not ready yet"
success "Sonarr installed at https://sonarr.$DOMAIN"
