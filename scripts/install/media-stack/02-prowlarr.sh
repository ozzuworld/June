#!/bin/bash
# Media Stack - Prowlarr Installation
# Installs Prowlarr indexer manager in media-stack namespace

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ -f "${ROOT_DIR}/config.env" ]; then source "${ROOT_DIR}/config.env"; fi
[ -z "$DOMAIN" ] && error "DOMAIN variable is not set."

NAMESPACE="media-stack"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"

log "Installing Prowlarr in $NAMESPACE namespace for domain: $DOMAIN"

verify_namespace "$NAMESPACE"

mkdir -p /mnt/ssd/media-configs/prowlarr
chown -R 1000:1000 /mnt/ssd/media-configs/prowlarr

log "Creating Prowlarr persistent volume..."
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: prowlarr-config-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "fast-ssd"
  hostPath:
    path: /mnt/ssd/media-configs/prowlarr
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prowlarr-config
  namespace: $NAMESPACE
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: "fast-ssd"
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prowlarr
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prowlarr
  template:
    metadata:
      labels:
        app: prowlarr
    spec:
      containers:
      - name: prowlarr
        image: lscr.io/linuxserver/prowlarr:latest
        ports:
        - containerPort: 9696
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
            memory: "256Mi"
            cpu: "250m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: prowlarr-config
---
apiVersion: v1
kind: Service
metadata:
  name: prowlarr
  namespace: $NAMESPACE
spec:
  selector:
    app: prowlarr
  ports:
  - port: 9696
    targetPort: 9696
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prowlarr-ingress
  namespace: $NAMESPACE
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - secretName: $WILDCARD_SECRET_NAME
    hosts:
    - prowlarr.$DOMAIN
  rules:
  - host: prowlarr.$DOMAIN
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: prowlarr
            port:
              number: 9696
EOF

kubectl wait --for=condition=ready pod -l app=prowlarr -n $NAMESPACE --timeout=300s || warn "Prowlarr not ready yet"
success "Prowlarr installed in $NAMESPACE namespace at https://prowlarr.$DOMAIN"
