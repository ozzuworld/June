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

# Load configuration
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
    error "DOMAIN variable is not set."
fi

log "Installing OpenCTI for domain: $DOMAIN"

# Certificate name
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"

# Ensure namespace
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# System requirements for OpenSearch
log "Setting vm.max_map_count for OpenSearch..."
sysctl -w vm.max_map_count=262144
if ! grep -q "vm.max_map_count=262144" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
fi

# Create storage with proper permissions
log "Creating storage directories..."
mkdir -p /mnt/opencti/{opensearch,minio,rabbitmq,redis}
chown -R 1000:1000 /mnt/opencti/opensearch
chown -R 1000:1000 /mnt/opencti/minio
chown -R 999:999 /mnt/opencti/rabbitmq
chmod -R 755 /mnt/opencti

# Generate passwords
OPENCTI_TOKEN=$(openssl rand -hex 32)
ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
HEALTH_KEY=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_ERLANG=$(openssl rand -hex 32)
MINIO_USER="opencti"
MINIO_PASSWORD=$(openssl rand -base64 16)

# Add Helm repo
log "Adding devops-ia Helm repository..."
helm repo add opencti https://devops-ia.github.io/helm-opencti 2>/dev/null || true
helm repo update

# Verify certificate
if kubectl get secret "$WILDCARD_SECRET_NAME" -n june-services &>/dev/null; then
    success "Wildcard certificate found: $WILDCARD_SECRET_NAME"
else
    warn "Wildcard certificate not found: $WILDCARD_SECRET_NAME"
fi

# Create values file - ALL FIXES APPLIED
log "Creating Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
# OpenCTI Platform Environment Variables (as KEY: VALUE map, not array!)
env:
  # APP OPENCTI
  APP__ADMIN__EMAIL: "${ADMIN_EMAIL}"
  APP__ADMIN__PASSWORD: "${ADMIN_PASSWORD}"
  APP__ADMIN__TOKEN: "${OPENCTI_TOKEN}"
  APP__BASE_PATH: "/"
  APP__GRAPHQL__PLAYGROUND__ENABLED: false
  APP__GRAPHQL__PLAYGROUND__FORCE_DISABLED_INTROSPECTION: false
  APP__HEALTH_ACCESS_KEY: "${HEALTH_KEY}"
  APP__TELEMETRY__METRICS__ENABLED: true
  NODE_OPTIONS: "--max-old-space-size=8096"
  PROVIDERS__LOCAL__STRATEGY: "LocalStrategy"
  
  # MINIO
  MINIO__ENDPOINT: "opencti-minio"
  MINIO__PORT: 9000
  MINIO__ACCESS_KEY: "${MINIO_USER}"
  MINIO__SECRET_KEY: "${MINIO_PASSWORD}"
  MINIO__USE_SSL: false
  
  # OPENSEARCH - CORRECT SERVICE NAME (without opencti- prefix)
  ELASTICSEARCH__URL: "http://opensearch-cluster-master:9200"
  
  # RABBITMQ
  RABBITMQ__HOSTNAME: "opencti-rabbitmq"
  RABBITMQ__PORT_MANAGEMENT: 15672
  RABBITMQ__PORT: 5672
  RABBITMQ__USERNAME: "opencti"
  RABBITMQ__PASSWORD: "${RABBITMQ_PASSWORD}"
  
  # REDIS - CORRECT SERVICE NAME
  REDIS__HOSTNAME: "opencti-redis"
  REDIS__PORT: 6379
  REDIS__MODE: "single"

# Resources for OpenCTI server
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

# OpenSearch Configuration - REMOVED INVALID SETTING
opensearch:
  enabled: true
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

# MinIO Configuration
minio:
  enabled: true
  mode: standalone
  
  auth:
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
    limits:
      memory: 2Gi
      cpu: 1000m

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
    username: "opencti"
    password: "${RABBITMQ_PASSWORD}"
    erlangCookie: "${RABBITMQ_ERLANG}"
  
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
EOF

log "Generated OpenCTI configuration:"
log "  Hostname: dark.${DOMAIN}"
log "  TLS Secret: ${WILDCARD_SECRET_NAME}"
log "  Admin Email: ${ADMIN_EMAIL}"
log "  OpenSearch: http://opensearch-cluster-master:9200"
log "  Redis: opencti-redis:6379"

# Install OpenCTI via Helm
log "Installing OpenCTI with Helm (this may take 10-15 minutes)..."
helm upgrade --install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --timeout 20m \
  --wait

log "Waiting for OpenSearch to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=opensearch \
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

log "Waiting for OpenCTI platform to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=opencti \
  -n june-services \
  --timeout=600s || warn "OpenCTI platform not ready yet"

# Get deployment status
log "OpenCTI deployment status:"
kubectl get pods -n june-services | grep -E "(opencti|opensearch|minio|rabbitmq)" || true

# Get ingress status
log "OpenCTI ingress status:"
kubectl get ingress -n june-services | grep opencti || warn "No OpenCTI ingress found"

# Save credentials
CREDS_FILE="/root/.opencti-credentials"
cat > "$CREDS_FILE" <<EOFCREDS
OpenCTI Credentials
===================
URL: https://dark.${DOMAIN}
Admin Email: ${ADMIN_EMAIL}
Admin Password: ${ADMIN_PASSWORD}
Admin Token: ${OPENCTI_TOKEN}
Health Access Key: ${HEALTH_KEY}

Service Endpoints:
  OpenSearch: http://opensearch-cluster-master:9200
  Redis: opencti-redis:6379
  RabbitMQ: opencti-rabbitmq:5672
  MinIO: opencti-minio:9000

MinIO: ${MINIO_USER} / ${MINIO_PASSWORD}
Redis Password: ${REDIS_PASSWORD}
RabbitMQ: opencti / ${RABBITMQ_PASSWORD}

Generated: $(date)
EOFCREDS

chmod 600 "$CREDS_FILE"

success "OpenCTI installed successfully!"
echo ""
echo "🔒 OpenCTI Cyber Threat Intelligence Platform:"
echo "  URL: https://dark.${DOMAIN}"
echo "  Email: ${ADMIN_EMAIL}"
echo "  Password: ${ADMIN_PASSWORD}"
echo ""
echo "📋 Credentials saved to: ${CREDS_FILE}"
echo ""
echo "🔍 Verify:"
echo "  kubectl get pods -n june-services | grep opencti"
echo "  kubectl logs -f deployment/opencti-server -n june-services"
echo ""
echo "⚠️  Note: First startup takes 3-5 minutes for all dependencies to initialize"
echo "  Monitor: kubectl get pods -n june-services -w"