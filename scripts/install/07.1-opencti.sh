#!/bin/bash
# June Platform - OpenCTI Installation Phase
# Installs OpenCTI Cyber Threat Intelligence Platform using Helm chart

set -e

# Colors
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

# Load configuration if not already loaded
if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    
    CONFIG_FILE="${ROOT_DIR}/config.env"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found: $CONFIG_FILE"
    fi
    
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

# Validate DOMAIN is set
if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set. Please check your config.env file."
fi

log "Installing OpenCTI Cyber Threat Intelligence Platform for domain: $DOMAIN"

# Calculate wildcard certificate secret name (same pattern as June platform)
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Using existing wildcard certificate: $WILDCARD_SECRET_NAME"

# Ensure june-services namespace exists
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Add OpenCTI Helm repository
log "Adding OpenCTI Helm repository..."
helm repo add opencti https://devops-ia.github.io/helm-opencti 2>/dev/null || true
helm repo update

# Create persistent volumes for OpenCTI components
log "Creating OpenCTI storage..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-data-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/data
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-redis-pv
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/redis
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-elasticsearch-pv
spec:
  capacity:
    storage: 30Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/elasticsearch
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-minio-pv
spec:
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/minio
    type: DirectoryOrCreate
EOF

# Generate random passwords for OpenCTI components
OPENCTI_ADMIN_TOKEN=$(openssl rand -hex 32)
OPENCTI_ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
OPENCTI_ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
REDIS_PASSWORD=$(openssl rand -base64 16)
MINIO_ROOT_PASSWORD=$(openssl rand -base64 16)

# Create secrets for OpenCTI
log "Creating OpenCTI secrets..."
kubectl create secret generic opencti-secrets \
  --from-literal=admin-token="$OPENCTI_ADMIN_TOKEN" \
  --from-literal=admin-password="$OPENCTI_ADMIN_PASSWORD" \
  --namespace june-services \
  --dry-run=client -o yaml | kubectl apply -f -

# Create values file for OpenCTI with wildcard cert
log "Creating OpenCTI Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
# OpenCTI Platform Configuration
opencti:
  replicaCount: 1
  image:
    repository: opencti/platform
    tag: latest
    pullPolicy: IfNotPresent
  
  # Environment variables
  env:
    - name: APP__ADMIN__EMAIL
      value: "${OPENCTI_ADMIN_EMAIL}"
    - name: APP__ADMIN__PASSWORD
      valueFrom:
        secretKeyRef:
          name: opencti-secrets
          key: admin-password
    - name: APP__ADMIN__TOKEN
      valueFrom:
        secretKeyRef:
          name: opencti-secrets
          key: admin-token
    - name: APP__BASE_PATH
      value: ""
    - name: NODE_OPTIONS
      value: "--max-old-space-size=8192"
  
  # Resources
  resources:
    requests:
      memory: 2Gi
      cpu: 1000m
    limits:
      memory: 8Gi
      cpu: 4000m
  
  # Persistence
  persistence:
    enabled: true
    storageClass: ""
    size: 10Gi

# Worker Configuration
worker:
  replicaCount: 3
  image:
    repository: opencti/worker
    tag: latest
  
  resources:
    requests:
      memory: 512Mi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 2000m

# Redis Configuration (Internal)
redis:
  enabled: true
  architecture: standalone
  auth:
    enabled: true
    password: "${REDIS_PASSWORD}"
  master:
    persistence:
      enabled: true
      storageClass: ""
      size: 5Gi

# Elasticsearch Configuration (Internal)
elasticsearch:
  enabled: true
  replicas: 1
  minimumMasterNodes: 1
  
  esJavaOpts: "-Xmx4g -Xms4g"
  
  resources:
    requests:
      cpu: 1000m
      memory: 4Gi
    limits:
      cpu: 2000m
      memory: 8Gi
  
  volumeClaimTemplate:
    accessModes: [ "ReadWriteOnce" ]
    storageClassName: ""
    resources:
      requests:
        storage: 30Gi
  
  # Elasticsearch security settings
  esConfig:
    elasticsearch.yml: |
      xpack.security.enabled: false

# MinIO Configuration (S3-compatible storage)
minio:
  enabled: true
  mode: standalone
  
  rootUser: opencti
  rootPassword: "${MINIO_ROOT_PASSWORD}"
  
  persistence:
    enabled: true
    storageClass: ""
    size: 20Gi
  
  resources:
    requests:
      memory: 512Mi
      cpu: 250m

# RabbitMQ Configuration (Message Queue)
rabbitmq:
  enabled: true
  auth:
    username: opencti
    password: "${REDIS_PASSWORD}"
    erlangCookie: "$(openssl rand -hex 32)"
  
  persistence:
    enabled: true
    storageClass: ""
    size: 5Gi
  
  resources:
    requests:
      memory: 512Mi
      cpu: 500m

# Ingress Configuration
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/websocket-services: "opencti"
  
  hosts:
    - host: dark.${DOMAIN}
      paths:
        - path: /
          pathType: Prefix
          backend:
            service:
              name: opencti
              port:
                number: 8080
  
  tls:
    - secretName: ${WILDCARD_SECRET_NAME}
      hosts:
        - dark.${DOMAIN}
EOF

# Show the generated values for verification
log "Generated OpenCTI configuration:"
log "  Hostname: dark.${DOMAIN}"
log "  TLS Secret: ${WILDCARD_SECRET_NAME}"
log "  Admin Email: ${OPENCTI_ADMIN_EMAIL}"

# Verify wildcard certificate exists
if kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services &>/dev/null; then
    success "Wildcard certificate found: $WILDCARD_SECRET_NAME"
else
    warn "Wildcard certificate not found: $WILDCARD_SECRET_NAME"
    warn "OpenCTI will still deploy, but HTTPS may not work until certificate is ready"
fi

# Set system requirements for Elasticsearch
log "Configuring system requirements for Elasticsearch..."
sysctl -w vm.max_map_count=1048575 || warn "Could not set vm.max_map_count"

# Make it persistent
if ! grep -q "vm.max_map_count=1048575" /etc/sysctl.conf; then
    echo "vm.max_map_count=1048575" >> /etc/sysctl.conf
fi

# Install OpenCTI via Helm
log "Installing OpenCTI with Helm (this may take several minutes)..."
helm upgrade --install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --wait \
  --timeout 20m

# Wait for OpenCTI platform to be ready
log "Waiting for OpenCTI platform to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=opencti,app.kubernetes.io/component=platform \
  -n june-services \
  --timeout=600s || warn "OpenCTI platform pod not ready yet"

# Wait for dependencies
log "Waiting for OpenCTI dependencies (Elasticsearch, Redis, MinIO)..."
sleep 30

# Get OpenCTI status
log "OpenCTI deployment status:"
kubectl get pods -n june-services -l app.kubernetes.io/name=opencti

# Verify ingress is created
log "OpenCTI ingress status:"
kubectl get ingress -n june-services | grep opencti || warn "No OpenCTI ingress found"

# Save credentials to file
CREDS_FILE="/root/.opencti-credentials"
cat > "$CREDS_FILE" <<EOF
OpenCTI Credentials
===================
URL: https://dark.${DOMAIN}
Admin Email: ${OPENCTI_ADMIN_EMAIL}
Admin Password: ${OPENCTI_ADMIN_PASSWORD}
Admin Token: ${OPENCTI_ADMIN_TOKEN}

MinIO (S3 Storage):
  Root User: opencti
  Root Password: ${MINIO_ROOT_PASSWORD}

Redis Password: ${REDIS_PASSWORD}
RabbitMQ Password: ${REDIS_PASSWORD}

Generated: $(date)
EOF

chmod 600 "$CREDS_FILE"

success "OpenCTI installed successfully!"
echo ""
echo "🔒 OpenCTI Cyber Threat Intelligence Platform:"
echo "  URL: https://dark.${DOMAIN}"
echo "  Admin Email: ${OPENCTI_ADMIN_EMAIL}"
echo "  Admin Password: ${OPENCTI_ADMIN_PASSWORD}"
echo ""
echo "📋 Credentials saved to: ${CREDS_FILE}"
echo ""
echo "📁 Storage Locations:"
echo "  Data: /mnt/opencti/data"
echo "  Redis: /mnt/opencti/redis"
echo "  Elasticsearch: /mnt/opencti/elasticsearch"
echo "  MinIO: /mnt/opencti/minio"
echo ""
echo "🔐 Certificate:"
echo "  Using shared wildcard certificate: ${WILDCARD_SECRET_NAME}"
echo "  Same certificate as api.$DOMAIN, idp.$DOMAIN, tv.$DOMAIN, etc."
echo ""
echo "🔍 Verify deployment:"
echo "  kubectl get pods -n june-services | grep opencti"
echo "  kubectl get ingress -n june-services | grep opencti"
echo ""
echo "⚠️  Note: First startup may take 5-10 minutes while Elasticsearch initializes"
echo "  Monitor progress: kubectl logs -f deployment/opencti-platform -n june-services"
