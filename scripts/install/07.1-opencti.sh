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

# Calculate wildcard certificate secret name
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
log "Using existing wildcard certificate: $WILDCARD_SECRET_NAME"

# Ensure june-services namespace exists
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Set system requirements for OpenSearch (persistent)
log "Configuring system requirements for OpenSearch..."
sysctl -w vm.max_map_count=262144 || warn "Could not set vm.max_map_count"

if ! grep -q "vm.max_map_count=262144" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
fi

# Create storage directories with proper permissions
log "Creating storage directories with proper permissions..."
mkdir -p /mnt/opencti/{data,opensearch,minio,rabbitmq,redis}
chown -R 1000:1000 /mnt/opencti/opensearch
chown -R 1000:1000 /mnt/opencti/minio
chown -R 999:999 /mnt/opencti/rabbitmq
chmod -R 755 /mnt/opencti

# Create persistent volumes
log "Creating OpenCTI persistent volumes..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencti-opensearch-pv
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

# Generate secure passwords
OPENCTI_ADMIN_TOKEN=$(openssl rand -hex 32)
OPENCTI_ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
OPENCTI_ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
REDIS_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_ERLANG_COOKIE=$(openssl rand -hex 32)
MINIO_ROOT_USER="opencti"
MINIO_ROOT_PASSWORD=$(openssl rand -base64 16)

# Add OpenCTI Helm repository
log "Adding OpenCTI Helm repository..."
helm repo add opencti https://opencti-platform.github.io/helm-charts 2>/dev/null || true
helm repo update

# Verify wildcard certificate exists
if kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services &>/dev/null; then
    success "Wildcard certificate found: $WILDCARD_SECRET_NAME"
else
    warn "Wildcard certificate not found: $WILDCARD_SECRET_NAME"
    warn "OpenCTI will still deploy, but HTTPS may not work until certificate is ready"
fi

# Create Helm values file with CORRECT service name references
log "Creating OpenCTI Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
# Global release name
nameOverride: "opencti"
fullnameOverride: "opencti"

# OpenCTI Platform Configuration
opencti:
  enabled: true
  
  image:
    repository: opencti/platform
    tag: "6.3.9"
    pullPolicy: IfNotPresent
  
  replicaCount: 1
  
  env:
    - name: APP__PORT
      value: "4000"
    - name: APP__BASE_PATH
      value: ""
    - name: APP__ADMIN__EMAIL
      value: "${OPENCTI_ADMIN_EMAIL}"
    - name: APP__ADMIN__PASSWORD
      value: "${OPENCTI_ADMIN_PASSWORD}"
    - name: APP__ADMIN__TOKEN
      value: "${OPENCTI_ADMIN_TOKEN}"
    - name: APP__HEALTH_ACCESS_KEY
      value: "${OPENCTI_ADMIN_TOKEN}"
    - name: NODE_OPTIONS
      value: "--max-old-space-size=8096"
    - name: APP__GRAPHQL__PLAYGROUND__ENABLED
      value: "false"
    - name: PROVIDERS__LOCAL__STRATEGY
      value: "LocalStrategy"
    - name: APP__TELEMETRY__METRICS__ENABLED
      value: "true"
    # CRITICAL: Correct service name references
    - name: ELASTICSEARCH__URL
      value: "http://opencti-opensearch-cluster-master:9200"
    - name: REDIS__HOSTNAME
      value: "opencti-redis-master"
    - name: REDIS__PORT
      value: "6379"
    - name: REDIS__PASSWORD
      value: "${REDIS_PASSWORD}"
    - name: RABBITMQ__HOSTNAME
      value: "opencti-rabbitmq"
    - name: RABBITMQ__PORT
      value: "5672"
    - name: RABBITMQ__PORT_MANAGEMENT
      value: "15672"
    - name: RABBITMQ__USERNAME
      value: "opencti"
    - name: RABBITMQ__PASSWORD
      value: "${RABBITMQ_PASSWORD}"
    - name: MINIO__ENDPOINT
      value: "opencti-minio:9000"
    - name: MINIO__PORT
      value: "9000"
    - name: MINIO__USE_SSL
      value: "false"
    - name: MINIO__ACCESS_KEY
      value: "${MINIO_ROOT_USER}"
    - name: MINIO__SECRET_KEY
      value: "${MINIO_ROOT_PASSWORD}"
  
  service:
    type: ClusterIP
    port: 80
    targetPort: 4000
  
  resources:
    requests:
      memory: 2Gi
      cpu: 1000m
    limits:
      memory: 8Gi
      cpu: 4000m

# Worker Configuration
worker:
  enabled: true
  replicaCount: 2
  
  image:
    repository: opencti/worker
    tag: "6.3.9"
  
  env:
    - name: OPENCTI_URL
      value: "http://opencti-server:80"
    - name: OPENCTI_TOKEN
      value: "${OPENCTI_ADMIN_TOKEN}"
    - name: WORKER_LOG_LEVEL
      value: "info"
  
  resources:
    requests:
      memory: 512Mi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 2000m

# OpenSearch Configuration (replaces Elasticsearch)
opensearch:
  enabled: true
  
  clusterName: "opencti"
  nodeGroup: "cluster-master"
  
  replicas: 1
  
  # CRITICAL: OpenSearch requires vm.max_map_count=262144
  sysctlInit:
    enabled: true
  
  config:
    opensearch.yml: |
      cluster.name: opencti-cluster
      network.host: 0.0.0.0
      bootstrap.memory_lock: false
      discovery.type: single-node
      plugins.security.disabled: true
      compatibility.override_main_response_version: true
  
  opensearchJavaOpts: "-Xms2g -Xmx2g"
  
  resources:
    requests:
      cpu: 1000m
      memory: 3Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  
  persistence:
    enabled: true
    storageClass: ""
    size: 30Gi
  
  # Init container to set permissions and sysctl
  extraInitContainers:
    - name: sysctl
      image: busybox:1.35
      imagePullPolicy: IfNotPresent
      command:
        - sh
        - -c
        - |
          set -xe
          DESIRED="262144"
          CURRENT=\$(sysctl -n vm.max_map_count)
          if [ "\$DESIRED" -gt "\$CURRENT" ]; then
            sysctl -w vm.max_map_count=\$DESIRED
          fi
      securityContext:
        privileged: true
        runAsUser: 0
    - name: chown
      image: busybox:1.35
      imagePullPolicy: IfNotPresent
      command:
        - sh
        - -c
        - chown -R 1000:1000 /usr/share/opensearch/data
      volumeMounts:
        - name: opensearch-cluster-master
          mountPath: /usr/share/opensearch/data
      securityContext:
        runAsUser: 0

# MinIO Configuration (S3-compatible storage)
minio:
  enabled: true
  mode: standalone
  
  image:
    repository: quay.io/minio/minio
    tag: RELEASE.2024-12-18T13-15-44Z
  
  rootUser: "${MINIO_ROOT_USER}"
  rootPassword: "${MINIO_ROOT_PASSWORD}"
  
  persistence:
    enabled: true
    storageClass: ""
    size: 20Gi
  
  resources:
    requests:
      memory: 512Mi
      cpu: 250m
    limits:
      memory: 2Gi
      cpu: 1000m
  
  # Create default bucket for OpenCTI
  buckets:
    - name: opencti-bucket
      policy: none
      purge: false
  
  # Init container to fix permissions
  extraInitContainers:
    - name: fix-permissions
      image: busybox:1.35
      command:
        - sh
        - -c
        - |
          chown -R 1000:1000 /export
          chmod -R 755 /export
      volumeMounts:
        - name: export
          mountPath: /export
      securityContext:
        runAsUser: 0
  
  securityContext:
    enabled: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000

# Redis Configuration
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
    
    resources:
      requests:
        memory: 256Mi
        cpu: 250m
      limits:
        memory: 1Gi
        cpu: 500m

# RabbitMQ Configuration
rabbitmq:
  enabled: true
  
  auth:
    username: opencti
    password: "${RABBITMQ_PASSWORD}"
    erlangCookie: "${RABBITMQ_ERLANG_COOKIE}"
  
  persistence:
    enabled: true
    storageClass: ""
    size: 5Gi
  
  extraConfiguration: |
    max_message_size = 536870912
    consumer_timeout = 86400000
  
  resources:
    requests:
      memory: 512Mi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 1000m

# Ingress Configuration
ingress:
  enabled: true
  className: nginx
  
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "500m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "600"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
  
  hosts:
    - host: dark.${DOMAIN}
      paths:
        - path: /
          pathType: Prefix
  
  tls:
    - secretName: ${WILDCARD_SECRET_NAME}
      hosts:
        - dark.${DOMAIN}

# Service Account
serviceAccount:
  create: true
  name: opencti
EOF

log "Generated OpenCTI configuration:"
log "  Hostname: dark.${DOMAIN}"
log "  TLS Secret: ${WILDCARD_SECRET_NAME}"
log "  Admin Email: ${OPENCTI_ADMIN_EMAIL}"
log "  Service URLs:"
log "    - OpenSearch: http://opencti-opensearch-cluster-master:9200"
log "    - Redis: opencti-redis-master:6379"
log "    - RabbitMQ: opencti-rabbitmq:5672"
log "    - MinIO: opencti-minio:9000"

# Install OpenCTI via Helm
log "Installing OpenCTI with Helm (this may take 10-15 minutes)..."
helm upgrade --install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --wait \
  --timeout 20m || {
    warn "Helm install timed out or failed. Checking pod status..."
    kubectl get pods -n june-services | grep opencti
    error "OpenCTI installation failed. Check logs with: kubectl logs -n june-services -l app.kubernetes.io/name=opencti"
  }

# Wait for core components
log "Waiting for OpenSearch to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/component=opensearch-cluster-master \
  -n june-services \
  --timeout=600s || warn "OpenSearch not ready yet"

log "Waiting for MinIO to be ready..."
kubectl wait --for=condition=ready pod \
  -l app=minio \
  -n june-services \
  --timeout=300s || warn "MinIO not ready yet"

log "Waiting for RabbitMQ to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=rabbitmq \
  -n june-services \
  --timeout=300s || warn "RabbitMQ not ready yet"

log "Waiting for Redis to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=redis \
  -n june-services \
  --timeout=300s || warn "Redis not ready yet"

log "Waiting for OpenCTI platform to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=opencti,opencti.component=server \
  -n june-services \
  --timeout=600s || warn "OpenCTI platform not ready yet"

# Get deployment status
log "OpenCTI deployment status:"
kubectl get pods -n june-services | grep -E "(opencti|opensearch|minio|rabbitmq|redis)" || true

# Verify services
log "OpenCTI services:"
kubectl get svc -n june-services | grep -E "(opencti|opensearch|minio|rabbitmq|redis)" || true

# Verify ingress
log "OpenCTI ingress status:"
kubectl get ingress -n june-services | grep opencti || warn "No OpenCTI ingress found"

# Save credentials
CREDS_FILE="/root/.opencti-credentials"
cat > "$CREDS_FILE" <<EOF
OpenCTI Credentials
===================
URL: https://dark.${DOMAIN}
Admin Email: ${OPENCTI_ADMIN_EMAIL}
Admin Password: ${OPENCTI_ADMIN_PASSWORD}
Admin Token: ${OPENCTI_ADMIN_TOKEN}

Service Endpoints (Internal):
  OpenSearch: http://opencti-opensearch-cluster-master:9200
  Redis: opencti-redis-master:6379
  RabbitMQ: opencti-rabbitmq:5672
  MinIO: opencti-minio:9000

MinIO (S3 Storage):
  Root User: ${MINIO_ROOT_USER}
  Root Password: ${MINIO_ROOT_PASSWORD}

Redis Password: ${REDIS_PASSWORD}
RabbitMQ Username: opencti
RabbitMQ Password: ${RABBITMQ_PASSWORD}
RabbitMQ Erlang Cookie: ${RABBITMQ_ERLANG_COOKIE}

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
echo "  OpenSearch: /mnt/opencti/opensearch"
echo "  MinIO: /mnt/opencti/minio"
echo "  RabbitMQ: /mnt/opencti/rabbitmq"
echo "  Redis: /mnt/opencti/redis"
echo ""
echo "🔐 Certificate:"
echo "  Using shared wildcard certificate: ${WILDCARD_SECRET_NAME}"
echo ""
echo "🔍 Verify deployment:"
echo "  kubectl get pods -n june-services | grep opencti"
echo "  kubectl get svc -n june-services | grep opencti"
echo "  kubectl logs -f deployment/opencti-server -n june-services"
echo ""
echo "⚠️  Note: First login may take 2-3 minutes after pods are ready"
