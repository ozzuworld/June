#!/bin/bash
# June Platform - June Dark OSINT + OpenCTI Integration
# Complete deployment script for K8s

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

log "Deploying June Dark OSINT Framework for domain: $DOMAIN"
WILDCARD_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"

# Step 1: Get OpenCTI credentials
log "Retrieving OpenCTI credentials..."
if [ ! -f "/root/.opencti-credentials" ]; then
    error "OpenCTI credentials not found. Please run 07.1-opencti.sh first"
fi

OPENCTI_TOKEN=$(grep "Token:" /root/.opencti-credentials | awk '{print $2}')
if [ -z "$OPENCTI_TOKEN" ]; then
    error "Could not extract OpenCTI token from credentials file"
fi
success "OpenCTI token retrieved"

# Step 2: Create namespace
log "Creating June Dark namespace..."
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/00-namespace.yaml

# Step 3: Create ConfigMaps
log "Creating ConfigMaps..."
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/01-configmap.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/14-postgres-init.yaml

# Step 4: Create storage
log "Creating persistent volumes..."
mkdir -p /mnt/june-dark/{elasticsearch,postgres,neo4j,minio,redis,rabbitmq}
chown -R 1000:1000 /mnt/june-dark/elasticsearch /mnt/june-dark/minio
chown -R 999:999 /mnt/june-dark/postgres /mnt/june-dark/neo4j
chmod -R 755 /mnt/june-dark

kubectl apply -f ${ROOT_DIR}/k8s/june-dark/02-storage.yaml
sleep 5

# Wait for PVCs to be created
log "Waiting for PVCs to be created..."
for i in {1..30}; do
    PVC_COUNT=$(kubectl get pvc -n june-dark 2>/dev/null | grep -c "Pending\|Bound" || echo "0")
    if [ "$PVC_COUNT" -ge 6 ]; then
        success "Found $PVC_COUNT PVCs"
        break
    fi
    sleep 2
done

# Create PVs for each PVC
log "Creating PersistentVolumes..."

# Elasticsearch PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-elasticsearch-pv
spec:
  capacity:
    storage: 50Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: elasticsearch-pvc
  hostPath:
    path: /mnt/june-dark/elasticsearch
    type: DirectoryOrCreate
EOF

# PostgreSQL PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-postgres-pv
spec:
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: postgres-pvc
  hostPath:
    path: /mnt/june-dark/postgres
    type: DirectoryOrCreate
EOF

# Neo4j PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-neo4j-pv
spec:
  capacity:
    storage: 30Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: neo4j-data-pvc
  hostPath:
    path: /mnt/june-dark/neo4j
    type: DirectoryOrCreate
EOF

# MinIO PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-minio-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: minio-pvc
  hostPath:
    path: /mnt/june-dark/minio
    type: DirectoryOrCreate
EOF

# Redis PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-redis-pv
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: redis-pvc
  hostPath:
    path: /mnt/june-dark/redis
    type: DirectoryOrCreate
EOF

# RabbitMQ PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: june-dark-rabbitmq-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: june-dark
    name: rabbitmq-pvc
  hostPath:
    path: /mnt/june-dark/rabbitmq
    type: DirectoryOrCreate
EOF

success "PersistentVolumes created"

# Step 5: Deploy infrastructure services
log "Deploying infrastructure services (Elasticsearch, PostgreSQL, Neo4j, Redis, RabbitMQ, MinIO)..."
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/03-elasticsearch.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/04-postgres.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/05-neo4j.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/06-redis-rabbitmq.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/07-minio.yaml

log "Waiting for infrastructure services to be ready (2-3 minutes)..."
sleep 120

# Wait for infrastructure pods
log "Checking infrastructure health..."
kubectl wait --for=condition=ready pod \
    -l app=elasticsearch \
    -n june-dark \
    --timeout=300s || warn "Elasticsearch not ready yet"

kubectl wait --for=condition=ready pod \
    -l app=postgres \
    -n june-dark \
    --timeout=300s || warn "PostgreSQL not ready yet"

kubectl wait --for=condition=ready pod \
    -l app=neo4j \
    -n june-dark \
    --timeout=300s || warn "Neo4j not ready yet"

kubectl wait --for=condition=ready pod \
    -l app=redis \
    -n june-dark \
    --timeout=180s || warn "Redis not ready yet"

kubectl wait --for=condition=ready pod \
    -l app=rabbitmq \
    -n june-dark \
    --timeout=180s || warn "RabbitMQ not ready yet"

success "Infrastructure services deployed"

# Step 6: Build and push Docker images (if needed)
log "Checking for Docker images..."
warn "Note: You need to build and push Docker images for June Dark services"
warn "Images needed:"
warn "  - ghcr.io/ozzuworld/june-dark-orchestrator:latest"
warn "  - ghcr.io/ozzuworld/june-dark-collector:latest"
warn "  - ghcr.io/ozzuworld/june-dark-enricher:latest"
warn "  - ghcr.io/ozzuworld/june-dark-ops-ui:latest"
warn "  - ghcr.io/ozzuworld/june-dark-opencti-connector:latest"
warn ""
warn "Run the build script or skip this if images are already pushed"

read -p "Continue with deployment? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    error "Deployment cancelled. Please build images first."
fi

# Step 7: Deploy June Dark application services
log "Deploying June Dark application services..."
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/08-orchestrator.yaml
sleep 30

kubectl apply -f ${ROOT_DIR}/k8s/june-dark/09-collector.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/10-enricher.yaml
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/11-ops-ui.yaml

log "Waiting for application services to be ready..."
sleep 60

# Step 8: Configure OpenCTI connector with token
log "Configuring OpenCTI connector..."
kubectl create secret generic opencti-connector-secret \
    --from-literal=OPENCTI_URL="https://dark.${DOMAIN}" \
    --from-literal=OPENCTI_TOKEN="${OPENCTI_TOKEN}" \
    -n june-dark \
    --dry-run=client -o yaml | kubectl apply -f -

success "OpenCTI connector configured"

# Step 9: Deploy OpenCTI connector
log "Deploying OpenCTI connector..."
kubectl apply -f ${ROOT_DIR}/k8s/june-dark/12-opencti-connector.yaml

log "Waiting for connector to be ready..."
sleep 30

# Step 10: Create ingress with proper domain
log "Creating ingress..."
sed -e "s/DOMAIN/${DOMAIN}/g" \
    -e "s/WILDCARD_SECRET_NAME/${WILDCARD_SECRET_NAME}/g" \
    ${ROOT_DIR}/k8s/june-dark/13-ingress.yaml | kubectl apply -f -

success "Ingress created"

# Step 11: Wait for all pods to be ready
log "Final health check..."
kubectl get pods -n june-dark

# Save deployment info
cat > /root/.june-dark-deployment <<EOF
June Dark OSINT Framework Deployment
====================================
Deployed: $(date)
Domain: ${DOMAIN}

Access Points:
- Main API: https://june.${DOMAIN}
- Operations Dashboard: https://june.${DOMAIN}/dashboard
- Kibana: https://kibana.${DOMAIN}
- Neo4j: https://neo4j.${DOMAIN}
- OpenCTI: https://dark.${DOMAIN}

Services:
- Orchestrator: http://orchestrator.june-dark:8080
- Enricher: http://enricher.june-dark:9010
- Ops UI: http://ops-ui.june-dark:8090

Infrastructure:
- Elasticsearch: http://elasticsearch.june-dark:9200
- PostgreSQL: postgres.june-dark:5432
- Neo4j: bolt://neo4j.june-dark:7687
- Redis: redis.june-dark:6379
- RabbitMQ: amqp://rabbitmq.june-dark:5672
- MinIO: http://minio.june-dark:9000

Credentials:
- PostgreSQL: juneadmin / juneP@ssw0rd2024
- Neo4j: neo4j / juneN3o4j2024
- RabbitMQ: juneadmin / juneR@bbit2024
- MinIO: juneadmin / juneM1ni0P@ss2024

OpenCTI Integration:
- Connector: june-dark-opencti-connector
- Status: Check with: kubectl logs -f deployment/opencti-connector -n june-dark

Monitoring:
kubectl get pods -n june-dark
kubectl logs -f deployment/orchestrator -n june-dark
kubectl logs -f deployment/opencti-connector -n june-dark
EOF

chmod 600 /root/.june-dark-deployment

success "June Dark OSINT Framework deployed!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 June Dark OSINT Framework"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Access Points:"
echo "  Main API:      https://june.${DOMAIN}"
echo "  Dashboard:     https://june.${DOMAIN}/dashboard"
echo "  Kibana:        https://kibana.${DOMAIN}"
echo "  Neo4j:         https://neo4j.${DOMAIN}"
echo "  OpenCTI:       https://dark.${DOMAIN}"
echo ""
echo "🔗 OpenCTI Integration:"
echo "  Status: Active"
echo "  Connector: june-dark-opencti-connector"
echo "  Check logs: kubectl logs -f deployment/opencti-connector -n june-dark"
echo ""
echo "📊 Current Pods:"
kubectl get pods -n june-dark
echo ""
echo "💾 Deployment info saved to: /root/.june-dark-deployment"
echo ""
echo "⏳ Allow 2-3 more minutes for all services to fully initialize"
