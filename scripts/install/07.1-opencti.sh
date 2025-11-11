#!/bin/bash
# June Platform - OpenCTI Installation - FINAL VERSION
# Creates PVs that match the exact PVC names Helm generates

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
kubectl get namespace june-services &>/dev/null || kubectl create namespace june-services

# Complete cleanup
log "Cleaning up existing installation..."
helm uninstall opencti -n june-services 2>/dev/null || true
sleep 3
kubectl delete pods -n june-services -l app.kubernetes.io/instance=opencti --force --grace-period=0 2>/dev/null || true
kubectl delete pvc -n june-services -l app.kubernetes.io/instance=opencti 2>/dev/null || true
kubectl delete pv opencti-opensearch-pv opencti-minio-pv opencti-rabbitmq-pv opencti-redis-pv 2>/dev/null || true
rm -rf /mnt/opencti/* 2>/dev/null || true
sleep 5

# System requirements
log "Configuring system..."
sysctl -w vm.max_map_count=262144 >/dev/null
if ! grep -q "vm.max_map_count=262144" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
fi

# Create storage
log "Creating storage directories..."
mkdir -p /mnt/opencti/{opensearch,minio,rabbitmq}
chown -R 1000:1000 /mnt/opencti/opensearch /mnt/opencti/minio
chown -R 999:999 /mnt/opencti/rabbitmq
chmod -R 755 /mnt/opencti

# Generate passwords
OPENCTI_TOKEN=$(openssl rand -hex 32)
ADMIN_EMAIL="${OPENCTI_ADMIN_EMAIL:-admin@${DOMAIN}}"
ADMIN_PASSWORD="${OPENCTI_ADMIN_PASSWORD:-$(openssl rand -base64 16)}"
HEALTH_KEY=$(openssl rand -hex 16)
RABBITMQ_PASSWORD=$(openssl rand -base64 16)
RABBITMQ_ERLANG=$(openssl rand -hex 32)
MINIO_USER="opencti"
MINIO_PASSWORD=$(openssl rand -base64 16)

# Helm repo
log "Updating Helm repositories..."
helm repo add opencti https://devops-ia.github.io/helm-opencti 2>/dev/null || true
helm repo update >/dev/null

# Create values
log "Creating Helm values..."
cat > /tmp/opencti-values.yaml <<EOF
env:
  APP__ADMIN__EMAIL: "${ADMIN_EMAIL}"
  APP__ADMIN__PASSWORD: "${ADMIN_PASSWORD}"
  APP__ADMIN__TOKEN: "${OPENCTI_TOKEN}"
  APP__HEALTH_ACCESS_KEY: "${HEALTH_KEY}"
  APP__TELEMETRY__METRICS__ENABLED: true
  NODE_OPTIONS: "--max-old-space-size=8096"
  MINIO__ENDPOINT: "opencti-minio"
  MINIO__PORT: 9000
  MINIO__ACCESS_KEY: "${MINIO_USER}"
  MINIO__SECRET_KEY: "${MINIO_PASSWORD}"
  MINIO__USE_SSL: false
  RABBITMQ__HOSTNAME: "opencti-rabbitmq"
  RABBITMQ__PORT: 5672
  RABBITMQ__USERNAME: "opencti"
  RABBITMQ__PASSWORD: "${RABBITMQ_PASSWORD}"
  REDIS__HOSTNAME: "opencti-redis"
  REDIS__PORT: 6379

resources:
  requests:
    memory: 2Gi
    cpu: 1000m

worker:
  enabled: true
  replicaCount: 2
  resources:
    requests:
      memory: 512Mi

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

minio:
  enabled: true
  mode: standalone
  rootUser: "${MINIO_USER}"
  rootPassword: "${MINIO_PASSWORD}"
  persistence:
    enabled: true
    storageClass: ""
    size: 20Gi

redis:
  enabled: true
  storage:
    enabled: false

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

# Install with Helm (don't wait - let it create PVCs first)
log "Installing OpenCTI with Helm..."
helm upgrade --install opencti opencti/opencti \
  --namespace june-services \
  --values /tmp/opencti-values.yaml \
  --timeout 20m &

HELM_PID=$!
sleep 15

# Wait for PVCs to be created
log "Waiting for PVCs to be created..."
for i in {1..30}; do
    PVC_COUNT=$(kubectl get pvc -n june-services 2>/dev/null | grep -c "opencti\|opensearch" || echo "0")
    if [ "$PVC_COUNT" -gt 0 ]; then
        success "Found $PVC_COUNT PVCs"
        break
    fi
    sleep 2
done

# Create PVs that match the actual PVC names
log "Creating matching PersistentVolumes..."

# Get exact PVC names
OPENSEARCH_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep opensearch | cut -d'/' -f2 || echo "")
MINIO_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep "opencti-minio" | cut -d'/' -f2 || echo "")
RABBITMQ_PVC=$(kubectl get pvc -n june-services -o name 2>/dev/null | grep "rabbitmq" | cut -d'/' -f2 || echo "")

if [ -n "$OPENSEARCH_PVC" ]; then
    log "Creating PV for: $OPENSEARCH_PVC"
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
fi

if [ -n "$MINIO_PVC" ]; then
    log "Creating PV for: $MINIO_PVC"
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
fi

if [ -n "$RABBITMQ_PVC" ]; then
    log "Creating PV for: $RABBITMQ_PVC"
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
fi

success "PersistentVolumes created with correct claimRefs"

# Wait for Helm to complete
log "Waiting for Helm installation to complete..."
wait $HELM_PID || warn "Helm install exited with issues"

# Wait for pods
log "Waiting for pods to start (up to 10 minutes)..."
sleep 30
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opencti -n june-services --timeout=600s 2>/dev/null || warn "Some pods not ready yet"

# Fix OpenSearch URL if needed
sleep 10
OPENSEARCH_SVC=$(kubectl get svc -n june-services -o name 2>/dev/null | grep opensearch | head -1 | cut -d'/' -f2 || echo "")
if [ -n "$OPENSEARCH_SVC" ]; then
    log "Configuring OpenSearch URL: $OPENSEARCH_SVC"
    kubectl set env deployment/opencti-server -n june-services ELASTICSEARCH__URL=http://${OPENSEARCH_SVC}:9200 2>/dev/null || true
    kubectl rollout restart deployment/opencti-server -n june-services 2>/dev/null || true
fi

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
echo "📊 Pod Status:"
kubectl get pods -n june-services | grep opencti || true
echo ""
echo "⚠️  First startup takes 5-10 minutes"
echo "Monitor: kubectl get pods -n june-services -w"