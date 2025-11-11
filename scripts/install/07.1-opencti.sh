#!/bin/bash
# June Platform - OpenCTI Installation - WORKING VERSION
# This script uses lessons learned from debugging to deploy OpenCTI correctly

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
    source "$CONFIG_FILE"
fi

if [ -z "$DOMAIN" ]; then
    error "DOMAIN variable is not set"
fi

log "Installing OpenCTI for domain: $DOMAIN"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"

# STEP 1: Complete cleanup
log "Performing complete cleanup..."
helm uninstall opencti -n june-services 2>/dev/null || true
sleep 5
kubectl delete pods -n june-services -l app.kubernetes.io/instance=opencti --force --grace-period=0 2>/dev/null || true
kubectl delete pvc -n june-services -l app.kubernetes.io/instance=opencti 2>/dev/null || true
kubectl delete pv opencti-opensearch-pv opencti-minio-pv opencti-rabbitmq-pv 2>/dev/null || true
rm -rf /mnt/opencti/* 2>/dev/null || true
sleep 10

# System setup
log "Configuring system..."
sysctl -w vm.max_map_count=262144 >/dev/null
mkdir -p /mnt/opencti/{opensearch,minio,rabbitmq}
chown -R 1000:1000 /mnt/opencti/opensearch /mnt/opencti/minio
chown -R 999:999 /mnt/opencti/rabbitmq
chmod -R 755 /mnt/opencti

# Generate passwords - use defaults for MinIO to match chart
OPENCTI_TOKEN=$(openssl rand -hex 32)
ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
HEALTH_KEY=$(openssl rand -hex 16)
RABBITMQ_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_ERLANG=$(openssl rand -hex 32)

# Helm repo
helm repo add opencti https://devops-ia.github.io/helm-opencti 2>/dev/null || true
helm repo update >/dev/null 2>&1

# Create Helm values with CORRECT service names and LOW resource requests
log "Creating Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
env:
  APP__ADMIN__EMAIL: "${ADMIN_EMAIL}"
  APP__ADMIN__PASSWORD: "${ADMIN_PASSWORD}"
  APP__ADMIN__TOKEN: "${OPENCTI_TOKEN}"
  APP__HEALTH_ACCESS_KEY: "${HEALTH_KEY}"
  APP__TELEMETRY__METRICS__ENABLED: true
  NODE_OPTIONS: "--max-old-space-size=4096"
  MINIO__ENDPOINT: "opencti-minio"
  MINIO__PORT: 9000
  MINIO__ACCESS_KEY: "ChangeMe"
  MINIO__SECRET_KEY: "ChangeMe"
  MINIO__USE_SSL: false
  ELASTICSEARCH__URL: "http://opensearch-cluster-master:9200"
  RABBITMQ__HOSTNAME: "opencti-rabbitmq"
  RABBITMQ__PORT: 5672
  RABBITMQ__USERNAME: "opencti"
  RABBITMQ__PASSWORD: "${RABBITMQ_PASSWORD}"
  REDIS__HOSTNAME: "opencti-redis"
  REDIS__PORT: 6379

resources:
  requests:
    memory: 1Gi
    cpu: 500m
  limits:
    memory: 4Gi
    cpu: 2000m

worker:
  enabled: true
  replicaCount: 1
  resources:
    requests:
      memory: 256Mi
      cpu: 250m
    limits:
      memory: 1Gi
      cpu: 1000m

opensearch:
  enabled: true
  singleNode: true
  replicas: 1
  sysctlInit:
    enabled: true
  opensearchJavaOpts: "-Xms1g -Xmx1g"
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
      cpu: 500m
      memory: 2Gi
    limits:
      cpu: 1000m
      memory: 3Gi

minio:
  enabled: true
  mode: standalone
  rootUser: "ChangeMe"
  rootPassword: "ChangeMe"
  persistence:
    enabled: true
    storageClass: ""
    size: 20Gi
  resources:
    requests:
      memory: 256Mi
      cpu: 100m
    limits:
      memory: 512Mi
      cpu: 500m

redis:
  enabled: true
  storage:
    enabled: false
  resources:
    requests:
      memory: 128Mi
      cpu: 100m

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
      memory: 256Mi
      cpu: 200m
    limits:
      memory: 512Mi
      cpu: 500m

ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "500m"
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

# Install with Helm in background
log "Starting Helm installation..."
helm install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --timeout 20m &
HELM_PID=$!

# Wait for PVCs to be created
sleep 20
log "Waiting for PVCs..."
for i in {1..30}; do
    PVC_COUNT=$(kubectl get pvc -n june-services 2>/dev/null | grep -c "opencti\|opensearch" || echo "0")
    if [ "$PVC_COUNT" -ge 2 ]; then
        success "Found $PVC_COUNT PVCs"
        break
    fi
    sleep 2
done

# Create matching PVs
log "Creating PersistentVolumes..."
OPENSEARCH_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep opensearch | cut -d'/' -f2 || echo "")
MINIO_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep "minio" | grep -v console | cut -d'/' -f2 || echo "")
RABBITMQ_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep "rabbitmq" | cut -d'/' -f2 || echo "")

if [ -n "$OPENSEARCH_PVC" ]; then
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
  claimRef:
    namespace: june-services
    name: ${OPENSEARCH_PVC}
  hostPath:
    path: /mnt/opencti/opensearch
    type: DirectoryOrCreate
EOF
    success "Created PV for $OPENSEARCH_PVC"
fi

if [ -n "$MINIO_PVC" ]; then
    cat <<EOF | kubectl apply -f -
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
  claimRef:
    namespace: june-services
    name: ${MINIO_PVC}
  hostPath:
    path: /mnt/opencti/minio
    type: DirectoryOrCreate
EOF
    success "Created PV for $MINIO_PVC"
fi

if [ -n "$RABBITMQ_PVC" ]; then
    cat <<EOF | kubectl apply -f -
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
  claimRef:
    namespace: june-services
    name: ${RABBITMQ_PVC}
  hostPath:
    path: /mnt/opencti/rabbitmq
    type: DirectoryOrCreate
EOF
    success "Created PV for $RABBITMQ_PVC"
fi

# Wait for Helm
log "Waiting for Helm to complete..."
wait $HELM_PID || warn "Helm had issues"

# Wait for pods to start
log "Waiting for pods (5-10 minutes)..."
sleep 60
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opencti -n june-services --timeout=600s 2>/dev/null || warn "Some pods not ready"

# Save credentials
cat > /root/.opencti-credentials <<EOFCREDS
OpenCTI Credentials
===================
URL: https://dark.${DOMAIN}
Email: ${ADMIN_EMAIL}
Password: ${ADMIN_PASSWORD}
Token: ${OPENCTI_TOKEN}

Generated: $(date)
EOFCREDS
chmod 600 /root/.opencti-credentials

success "OpenCTI installation complete!"
echo ""
echo "🔒 URL: https://dark.${DOMAIN}"
echo "📧 Email: ${ADMIN_EMAIL}"
echo "🔑 Password: ${ADMIN_PASSWORD}"
echo ""
echo "📊 Status:"
kubectl get pods -n june-services | grep opencti || true
echo ""
echo "⏳ Wait 5-10 minutes for all services to fully start"
echo "📋 Monitor: kubectl get pods -n june-services -w"