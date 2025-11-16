#!/bin/bash
# June Platform - Storage Setup
# Creates optimized storage structure and classes for SSD and HDD

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

log "Setting up optimized storage structure..."

# Step 1: Create SSD directory structure (250GB)
log "Creating SSD directories (/mnt/ssd)..."
mkdir -p /mnt/ssd/{postgresql,redis,elasticsearch,neo4j,rabbitmq,opensearch,jellyfin-config}
chown -R 1000:1000 /mnt/ssd/{elasticsearch,neo4j,opensearch,jellyfin-config}
chown -R 999:999 /mnt/ssd/{postgresql,rabbitmq}
chmod -R 755 /mnt/ssd
success "SSD directories created"

# Step 2: Create HDD directory structure (1TB)
log "Creating HDD directories (/mnt/hdd)..."
mkdir -p /mnt/hdd/{jellyfin-media,minio-artifacts,backups,logs}
chown -R 1000:1000 /mnt/hdd/*
chmod -R 755 /mnt/hdd
success "HDD directories created"

# Step 3: Wait for Kubernetes to be ready
log "Waiting for Kubernetes to be ready..."
for i in {1..30}; do
    if kubectl get nodes &>/dev/null; then
        success "Kubernetes is ready"
        break
    fi
    sleep 2
done

# Step 4: Create storage classes
log "Creating storage classes..."

cat <<EOF | kubectl apply -f -
---
# Fast SSD Storage Class
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain

---
# Slow HDD Storage Class
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain

---
# Legacy local-storage (for compatibility)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

success "Storage classes created"

# Step 5: Verify
log "Verifying storage setup..."
kubectl get sc

log "Storage structure:"
echo "  SSD (250GB): /mnt/ssd/"
echo "    - postgresql, redis, elasticsearch, neo4j, rabbitmq, opensearch, jellyfin-config"
echo ""
echo "  HDD (1TB): /mnt/hdd/"
echo "    - jellyfin-media, minio-artifacts, backups, logs"

success "Storage setup complete"
