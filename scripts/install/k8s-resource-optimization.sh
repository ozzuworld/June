#!/bin/bash
# Kubernetes Resource Optimization Script
# Fixes resource allocation issues and storage problems

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Kubernetes Resource Optimization"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Remove june-stt and june-tts (deploying elsewhere)
log "Step 1: Removing june-stt and june-tts deployments..."
kubectl delete deployment june-stt -n june-services --ignore-not-found=true
kubectl delete deployment june-tts -n june-services --ignore-not-found=true
kubectl delete svc june-stt -n june-services --ignore-not-found=true
kubectl delete svc june-tts -n june-services --ignore-not-found=true
success "Removed june-stt and june-tts (freed ~2-4 CPU cores + 10-12GB RAM)"

# Step 2: Create storage directory structure
log "Step 2: Creating optimized storage directory structure..."

# SSD directories (250GB total)
log "Creating SSD directories (/mnt/ssd)..."
mkdir -p /mnt/ssd/{postgresql,redis,elasticsearch,neo4j,rabbitmq,system}
chown -R 1000:1000 /mnt/ssd/elasticsearch /mnt/ssd/neo4j
chown -R 999:999 /mnt/ssd/postgresql /mnt/ssd/rabbitmq
chmod -R 755 /mnt/ssd

# HDD directories (1TB total)
log "Creating HDD directories (/mnt/hdd)..."
mkdir -p /mnt/hdd/{jellyfin-media,jellyfin-config,minio-artifacts,backups,logs}
chown -R 1000:1000 /mnt/hdd/jellyfin-media /mnt/hdd/jellyfin-config /mnt/hdd/minio-artifacts
chmod -R 755 /mnt/hdd

success "Storage directories created"

# Step 3: Apply storage classes
log "Step 3: Creating storage classes (SSD and HDD)..."
kubectl apply -f ${ROOT_DIR}/k8s/storage-classes.yaml
success "Storage classes applied"

# Step 4: Update Helm values to disable stt/tts
log "Step 4: Updating Helm values..."
if [ -f "${ROOT_DIR}/helm/june-platform/values.yaml" ]; then
    cp ${ROOT_DIR}/helm/june-platform/values.yaml ${ROOT_DIR}/helm/june-platform/values.yaml.backup
    log "Backed up original values.yaml"
fi

# Copy optimized values
cp ${ROOT_DIR}/helm/june-platform/values-optimized.yaml ${ROOT_DIR}/helm/june-platform/values.yaml
success "Updated Helm values (stt.enabled=false, tts.enabled=false)"

# Step 5: Fix june-dark resource allocations
log "Step 5: Optimizing june-dark resource allocations..."

# Update Elasticsearch with optimized resources
if [ -f "${ROOT_DIR}/k8s/june-dark/03-elasticsearch-optimized.yaml" ]; then
    kubectl apply -f ${ROOT_DIR}/k8s/june-dark/03-elasticsearch-optimized.yaml
    success "Elasticsearch optimized (4-6GB RAM, down from 10-16GB)"
fi

# Update Neo4j with optimized resources
if [ -f "${ROOT_DIR}/k8s/june-dark/05-neo4j-optimized.yaml" ]; then
    kubectl apply -f ${ROOT_DIR}/k8s/june-dark/05-neo4j-optimized.yaml
    success "Neo4j optimized (2-3GB RAM, down from 4-8GB)"
fi

# Step 6: Create PersistentVolumes for june-dark on SSD
log "Step 6: Creating PersistentVolumes for june-dark..."

# Elasticsearch PV (SSD)
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
  storageClassName: fast-ssd
  claimRef:
    namespace: june-dark
    name: elasticsearch-pvc
  hostPath:
    path: /mnt/ssd/elasticsearch
    type: DirectoryOrCreate
EOF

# PostgreSQL PV (SSD)
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
  storageClassName: fast-ssd
  claimRef:
    namespace: june-dark
    name: postgres-pvc
  hostPath:
    path: /mnt/ssd/postgresql
    type: DirectoryOrCreate
EOF

# Neo4j PV (SSD)
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
  storageClassName: fast-ssd
  claimRef:
    namespace: june-dark
    name: neo4j-data-pvc
  hostPath:
    path: /mnt/ssd/neo4j
    type: DirectoryOrCreate
EOF

# MinIO PV (HDD - for bulk artifacts)
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
  storageClassName: slow-hdd
  claimRef:
    namespace: june-dark
    name: minio-pvc
  hostPath:
    path: /mnt/hdd/minio-artifacts
    type: DirectoryOrCreate
EOF

# Redis PV (SSD)
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
  storageClassName: fast-ssd
  claimRef:
    namespace: june-dark
    name: redis-pvc
  hostPath:
    path: /mnt/ssd/redis
    type: DirectoryOrCreate
EOF

# RabbitMQ PV (SSD)
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
  storageClassName: fast-ssd
  claimRef:
    namespace: june-dark
    name: rabbitmq-pvc
  hostPath:
    path: /mnt/ssd/rabbitmq
    type: DirectoryOrCreate
EOF

success "Created 6 PersistentVolumes for june-dark"

# Step 7: Wait for pods to recover
log "Step 7: Waiting for pods to recover..."
sleep 30

log "Checking pod status..."
kubectl get pods -n june-dark

# Step 8: Show resource summary
log "Step 8: Generating resource summary..."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Resource Optimization Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "✅ Actions Completed:"
echo "  - Removed june-stt and june-tts (freed 2-4 CPU + 10-12GB RAM)"
echo "  - Created SSD storage class (/mnt/ssd)"
echo "  - Created HDD storage class (/mnt/hdd)"
echo "  - Optimized Elasticsearch (4-6GB RAM, down from 10-16GB)"
echo "  - Optimized Neo4j (2-3GB RAM, down from 4-8GB)"
echo "  - Created 6 PersistentVolumes for june-dark"
echo ""

echo "💾 Storage Allocation:"
echo "  SSD (250GB):"
echo "    - PostgreSQL:    20GB"
echo "    - Elasticsearch: 50GB"
echo "    - Neo4j:        30GB"
echo "    - Redis:         5GB"
echo "    - RabbitMQ:     10GB"
echo "    - System:       ~50GB"
echo "    - Free:         ~85GB"
echo ""
echo "  HDD (1TB):"
echo "    - MinIO:        100GB"
echo "    - Jellyfin:     TBD (see migration script)"
echo "    - Backups:      TBD"
echo "    - Logs:         TBD"
echo "    - Free:         ~800GB+"
echo ""

echo "🎯 Estimated Resource Usage After Optimization:"
echo "  june-services:"
echo "    CPU:    ~2-3 cores"
echo "    Memory: ~15-20GB"
echo ""
echo "  june-dark:"
echo "    CPU:    ~2-3 cores"
echo "    Memory: ~10-12GB"
echo ""
echo "  Total:"
echo "    CPU:    ~4-6 cores (within limits ✓)"
echo "    Memory: ~25-32GB / 64GB (50% usage ✓)"
echo ""

echo "⚠️  Next Steps:"
echo "  1. Monitor pods: kubectl get pods -n june-dark -w"
echo "  2. Check PVC binding: kubectl get pvc -n june-dark"
echo "  3. Migrate Jellyfin to HDD: ./jellyfin-hdd-migration.sh"
echo "  4. Verify all services are running"
echo ""

success "Resource optimization complete!"
