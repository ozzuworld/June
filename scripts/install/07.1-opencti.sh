#!/bin/bash
# June Platform - OpenCTI Complete Installation
# This script handles EVERYTHING: cleanup, PVs, correct service names, and deployment

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
    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found: $CONFIG_FILE"
    fi
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set"
fi

log "Installing OpenCTI for domain: $DOMAIN"

WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# STEP 1: Complete cleanup if reinstalling
log "Cleaning up any existing OpenCTI installation..."
helm uninstall opencti -n june-services 2>/dev/null || true
kubectl delete pods -n june-services -l app.kubernetes.io/instance=opencti --force --grace-period=0 2>/dev/null || true
kubectl delete pvc -n june-services -l app.kubernetes.io/instance=opencti 2>/dev/null || true
kubectl delete pv -l opencti-storage=true 2>/dev/null || true
rm -rf /mnt/opencti/* 2>/dev/null || true
sleep 5

# System requirements
log "Configuring system for OpenSearch..."
sysctl -w vm.max_map_count=262144
if ! grep -q "vm.max_map_count=262144" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
fi

# STEP 2: Create storage directories
log "Creating storage directories..."
mkdir -p /mnt/opencti/{opensearch,minio,rabbitmq,redis}
chown -R 1000:1000 /mnt/opencti/opensearch
chown -R 1000:1000 /mnt/opencti/minio  
chown -R 999:999 /mnt/opencti/rabbitmq
chmod -R 755 /mnt/opencti

# STEP 3: Create PersistentVolumes BEFORE Helm install
log "Creating PersistentVolumes..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-opensearch-pv
  labels:
    opencti-storage: "true"
spec:
  capacity:
    storage: 30Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/opensearch
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-minio-pv
  labels:
    opencti-storage: "true"
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
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-rabbitmq-pv
  labels:
    opencti-storage: "true"
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/opencti/rabbitmq
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-redis-pv
  labels:
    opencti-storage: "true"
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
EOF

success "PersistentVolumes created"
sleep 2

# STEP 4: Generate passwords
OPENCTI_TOKEN=$(openssl rand -hex 32)
ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
HEALTH_KEY=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_ERLANG=$(openssl rand -hex 32)
MINIO_USER="opencti"
MINIO_PASSWORD=$(openssl rand -base64 16)

# STEP 5: Add Helm repo
log "Adding Helm repository..."
helm repo add opencti https://devops-ia.github.io/helm-opencti 2>/dev/null || true
helm repo update

if kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services &>/dev/null; then
    success "Certificate found: $WILDCARD_SECRET_NAME"
fi

# STEP 6: Create values file with CORRECT service names
# The chart creates services as: opencti-<subchart>
# OpenSearch becomes: opencti-opensearch-cluster-master (due to opensearch chart naming)
# But we need to check what the actual service name is after deployment
log "Creating Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
env:
  APP__ADMIN__EMAIL: "${ADMIN_EMAIL}"
  APP__ADMIN__PASSWORD: "${ADMIN_PASSWORD}"
  APP__ADMIN__TOKEN: "${OPENCTI_TOKEN}"
  APP__BASE_PATH: "/"
  APP__GRAPHQL__PLAYGROUND__ENABLED: false
  APP__HEALTH_ACCESS_KEY: "${HEALTH_KEY}"
  APP__TELEMETRY__METRICS__ENABLED: true
  NODE_OPTIONS: "--max-old-space-size=8096"
  PROVIDERS__LOCAL__STRATEGY: "LocalStrategy"
  MINIO__ENDPOINT: "opencti-minio"
  MINIO__PORT: 9000
  MINIO__ACCESS_KEY: "${MINIO_USER}"
  MINIO__SECRET_KEY: "${MINIO_PASSWORD}"
  MINIO__USE_SSL: false
  RABBITMQ__HOSTNAME: "opencti-rabbitmq"
  RABBITMQ__PORT: 5672
  RABBITMQ__PORT_MANAGEMENT: 15672
  RABBITMQ__USERNAME: "opencti"
  RABBITMQ__PASSWORD: "${RABBITMQ_PASSWORD}"
  REDIS__HOSTNAME: "opencti-redis"
  REDIS__PORT: 6379
  REDIS__MODE: "single"

resources:
  requests:
    memory: 2Gi
    cpu: 1000m
  limits:
    memory: 8Gi
    cpu: 4000m

worker:
  enabled: true
  replicaCount: 2
  env:
    WORKER_LOG_LEVEL: "info"
    WORKER_TELEMETRY_ENABLED: true
  resources:
    requests:
      memory: 512Mi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 2000m

opensearch:
  enabled: true
  singleNode: true
  replicas: 1
  sysctlInit:
    enabled: true
  opensearchJavaOpts: "-Xms2g -Xmx2g"
  config:
    opensearch.yml: |
      cluster.name: opencti
      network.host: 0.0.0.0
      discovery.type: single-node
      plugins.security.disabled: true
  persistence:
    enabled: true
    storageClass: ""
    size: 30Gi
  resources:
    requests:
      cpu: 1000m
      memory: 3Gi
    limits:
      cpu: 2000m
      memory: 4Gi

minio:
  enabled: true
  mode: standalone
  rootUser: "${MINIO_USER}"
  rootPassword: "${MINIO_PASSWORD}"
  persistence:
    enabled: true
    storageClass: ""
    size: 20Gi
  resources:
    requests:
      memory: 512Mi
      cpu: 250m

redis:
  enabled: true
  storage:
    enabled: true
    storageClass: ""
    size: 5Gi
  extraArgs:
    - --cache_mode=true
  resources:
    requests:
      memory: 256Mi
      cpu: 250m

rabbitmq:
  enabled: true
  auth:
    username: "opencti"
    password: "${RABBITMQ_PASSWORD}"
    erlangCookie: "${RABBITMQ_ERLANG}"
  persistence:
    enabled: true
    storageClass: ""
    size: 5Gi
  resources:
    requests:
      memory: 512Mi
      cpu: 500m

ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "500m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
  hosts:
    - host: dark.${DOMAIN}
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: ${WILDCARD_SECRET_NAME}
      hosts:
        - dark.${DOMAIN}
EOF

log "Installing OpenCTI (this takes 10-15 minutes)..."
helm upgrade --install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --timeout 20m \
  --wait || {
    warn "Helm install had issues. Checking status..."
    kubectl get pods -n june-services | grep opencti
  }

# STEP 7: Fix ELASTICSEARCH__URL if needed (opensearch service naming)
log "Checking OpenSearch service name..."
sleep 10
OPENSEARCH_SVC=$(kubectl get svc -n june-services -o name | grep opensearch | head -1 | cut -d'/' -f2)
if [ -n "$OPENSEARCH_SVC" ]; then
    log "Found OpenSearch service: $OPENSEARCH_SVC"
    kubectl set env deployment/opencti-server -n june-services ELASTICSEARCH__URL=http://${OPENSEARCH_SVC}:9200
    kubectl rollout restart deployment/opencti-server -n june-services
else
    warn "No OpenSearch service found - check deployment"
fi

# STEP 8: Wait for components
log "Waiting for all components (up to 10 minutes)..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opencti -n june-services --timeout=600s || warn "OpenCTI pods not ready yet"

# Save credentials
cat > /root/.opencti-credentials <<EOFCREDS
OpenCTI Credentials
===================
URL: https://dark.${DOMAIN}
Email: ${ADMIN_EMAIL}
Password: ${ADMIN_PASSWORD}
Token: ${OPENCTI_TOKEN}

MinIO: ${MINIO_USER} / ${MINIO_PASSWORD}
RabbitMQ: opencti / ${RABBITMQ_PASSWORD}
Redis Password: ${REDIS_PASSWORD}

Generated: $(date)
EOFCREDS
chmod 600 /root/.opencti-credentials

success "OpenCTI installation complete!"
echo ""
echo "🔒 URL: https://dark.${DOMAIN}"
echo "📧 Email: ${ADMIN_EMAIL}"
echo "🔑 Password: ${ADMIN_PASSWORD}"
echo "📋 Credentials: /root/.opencti-credentials"
echo ""
echo "📊 Status:"
kubectl get pods -n june-services | grep opencti || true
echo ""
echo "⚠️  Note: Full startup takes 5-10 minutes for all dependencies"
echo "Monitor with: kubectl get pods -n june-services -w"