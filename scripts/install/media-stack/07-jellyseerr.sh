#!/bin/bash
# Media Stack - Jellyseerr Installation
set -e
source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN not set"

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Installing Jellyseerr in $NAMESPACE for $DOMAIN"
verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/jellyseerr
chown -R 1000:1000 /mnt/ssd/media-configs/jellyseerr

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: jellyseerr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/jellyseerr
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jellyseerr-config
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
  name: jellyseerr
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jellyseerr
  template:
    metadata:
      labels:
        app: jellyseerr
    spec:
      containers:
      - name: jellyseerr
        image: fallenbagel/jellyseerr:preview-OIDC
        ports:
        - containerPort: 5055
        env:
        - {name: TZ, value: "America/New_York"}
        volumeMounts:
        - {name: config, mountPath: /app/config}
        resources:
          requests: {memory: "128Mi", cpu: "50m"}
          limits: {memory: "256Mi", cpu: "250m"}
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: jellyseerr-config
---
apiVersion: v1
kind: Service
metadata:
  name: jellyseerr
  namespace: $NAMESPACE
spec:
  selector:
    app: jellyseerr
  ports:
  - port: 5055
    targetPort: 5055
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: jellyseerr-ingress
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts: [requests.$DOMAIN]
  rules:
  - host: requests.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service: {name: jellyseerr, port: {number: 5055}}
EOF

kubectl wait --for=condition=ready pod -l app=jellyseerr -n $NAMESPACE --timeout=300s || warn "Jellyseerr not ready yet"
success "Jellyseerr installed at https://requests.$DOMAIN"
