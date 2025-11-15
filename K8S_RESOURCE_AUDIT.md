# Kubernetes Resource Audit Report
## System: June Platform (ozzu.world)
**Date**: $(date)
**Cluster**: Single-node K8s
**Resources**: 8x GPU, 64GB RAM, 250GB SSD, 1TB HDD

---

## 🔴 Critical Issues Identified

### 1. **Pods in Pending State**
```
june-stt-6658f6d6f6-xx9fn         Pending (GPU + CPU resources)
june-tts-59f5f69568-2rrfw          Pending (GPU + CPU resources)
minio-b87c9b967-zvqp4 (june-dark)  Pending (Insufficient CPU)
neo4j-76fdfb9c95-tmsxj (june-dark) Pending (Unbound PVC)
```

**Root Cause**:
- june-stt requesting: 1 GPU + 1-2 CPU + 6GB RAM
- june-tts requesting: 1 GPU + 1-2 CPU + 4-6GB RAM
- Total GPU request = 2 (you have 8, but these won't be used)
- **Insufficient CPU** due to overcommitment

### 2. **Resource Overcommitment**

**Current Total Requests** (from running + pending pods):
```
CPU Requests:    ~8-10 cores (exceeds available)
Memory Requests: ~35-40GB (within 64GB but tight)
GPU Requests:    2 (june-stt + june-tts - NOT NEEDED)
```

**Available**:
- CPUs: Likely 4-8 cores (not visible, but scheduling failures indicate limit)
- RAM: 64GB
- GPU: 8 (not needed for june-stt/tts as deploying elsewhere)

### 3. **Storage Issues**

**No Storage Classes Defined**:
- All PVCs use `storageClassName: ""` (manual binding)
- No distinction between SSD and HDD
- Jellyfin media on SSD (wasting precious SSD space)

**Unbound PVCs in june-dark**:
```
elasticsearch-pvc  50Gi  - No PV created yet
postgres-pvc       20Gi  - No PV created yet
neo4j-data-pvc     30Gi  - No PV created yet
minio-pvc         100Gi  - No PV created yet
redis-pvc           5Gi  - No PV created yet
rabbitmq-pvc       10Gi  - No PV created yet
```
**Total**: 215Gi requested (exceeds 250GB SSD if all on SSD)

### 4. **Resource Waste**

- **june-stt**: Enabled but will deploy elsewhere → DELETE
- **june-tts**: Enabled but will deploy elsewhere → DELETE
- **Jellyfin media**: On SSD, should be on 1TB HDD

---

## 📊 Resource Allocation Analysis

### Current Allocation (june-services namespace)

| Pod | CPU Request | CPU Limit | Memory Request | Memory Limit | Status |
|-----|-------------|-----------|----------------|--------------|---------|
| jellyfin | ? | ? | ? | ? | Running |
| jellyseerr | ? | ? | ? | ? | Running |
| june-idp (Keycloak) | 200m | 500m | 512Mi | 1Gi | Running |
| june-orchestrator | 200m | 500m | 512Mi | 1Gi | Running |
| june-redis-master | ? | ? | ? | ? | Running |
| june-stt | **1000m** | **2000m** | **6Gi** | **6Gi** | **Pending** ❌ |
| june-tts | **1000m** | **2000m** | **4Gi** | **6Gi** | **Pending** ❌ |
| livekit | ? | ? | ? | ? | Running |
| opencti-server | ? | ? | ? | ? | Running |
| opencti-worker | ? | ? | ? | ? | Running |
| opensearch | ? | ? | ? | ? | Running |
| postgresql | ? | ? | ? | ? | Running |
| Media services | ? | ? | ? | ? | Running |

**Problems**:
- june-stt + june-tts requesting **2-4 CPU cores + 10-12GB RAM** for nothing
- They also request **2 GPUs** that won't be used

### June Dark Allocation (june-dark namespace)

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|-------------|-----------|----------------|--------------|
| Elasticsearch | 2000m | 4000m | **10Gi** | **16Gi** |
| PostgreSQL | 500m | 2000m | 2Gi | 4Gi |
| Neo4j | 1000m | 2000m | 4Gi | 8Gi |
| Redis | 100m | 500m | 512Mi | 1Gi |
| RabbitMQ | 200m | 1000m | 1Gi | 2Gi |
| MinIO | 200m | 500m | 512Mi | 1Gi |
| **TOTAL** | **4000m** | **10000m** | **~18Gi** | **~32Gi** |

**Problems**:
- **Elasticsearch requesting 10-16GB** (too much for shared cluster)
- **Neo4j requesting 4-8GB** (can be reduced)
- **Total memory** with june-services = likely exceeding 64GB

---

## ✅ Recommended Fixes

### Immediate Actions

1. **Disable june-stt and june-tts** (deploying elsewhere)
   - Frees: ~2-4 CPU cores + 10-12GB RAM + 2 GPUs

2. **Create Storage Classes**
   - `fast-ssd`: For databases (PostgreSQL, Redis, ES data)
   - `slow-hdd`: For media (Jellyfin), logs, backups

3. **Move Jellyfin Media to HDD**
   - Frees: ~50-100GB SSD space

4. **Optimize june-dark Resources**
   - Reduce Elasticsearch to 4-6GB RAM
   - Reduce Neo4j to 2-4GB RAM
   - Reduce CPU limits

5. **Create PVs for june-dark**
   - Bind PVCs properly

### Resource Optimization Plan

**Optimized june-dark allocation**:
```yaml
Elasticsearch: 1000m CPU, 4Gi RAM (down from 10Gi)
PostgreSQL:    500m CPU,  2Gi RAM (same)
Neo4j:         500m CPU,  2Gi RAM (down from 4Gi)
Redis:         100m CPU,  512Mi RAM (same)
RabbitMQ:      200m CPU,  1Gi RAM (same)
MinIO:         100m CPU,  512Mi RAM (same)
---
TOTAL:         2400m CPU, ~10Gi RAM (vs 18Gi before)
```

**Benefits**:
- Frees 8GB RAM
- Reduces CPU pressure
- Still functional for OSINT workloads

---

## 📋 Storage Allocation Plan

### SSD (250GB) - Fast Storage
```
/mnt/ssd/
├── postgresql/          20GB  (Keycloak + june-dark)
├── redis/               5GB   (All Redis instances)
├── elasticsearch/       50GB  (OpenCTI + june-dark indexes)
├── neo4j/              30GB  (june-dark graph)
├── rabbitmq/           10GB  (june-dark + OpenCTI queues)
├── system/             50GB  (OS + containers)
└── reserved/           85GB  (free space)
---
TOTAL USED:            ~165GB / 250GB
```

### HDD (1TB) - Bulk Storage
```
/mnt/hdd/
├── jellyfin-media/    500GB  (movies, TV shows)
├── jellyfin-config/    10GB  (metadata, transcodes)
├── minio-artifacts/   100GB  (june-dark collected data)
├── backups/           100GB  (database backups)
├── logs/               50GB  (application logs)
└── reserved/          240GB  (free space)
---
TOTAL USED:            ~760GB / 1TB
```

---

## 🎯 Implementation Priority

1. **HIGH**: Disable june-stt & june-tts (immediate)
2. **HIGH**: Create storage classes (immediate)
3. **MEDIUM**: Optimize june-dark resources (after storage fix)
4. **MEDIUM**: Move Jellyfin to HDD (can do anytime)
5. **LOW**: Fine-tune other services (optional)

---

## 📝 Next Steps

See companion files:
1. `k8s-optimization-plan.sh` - Automated fix script
2. `values-optimized.yaml` - Optimized Helm values
3. `storage-classes.yaml` - SSD/HDD storage classes
4. `jellyfin-hdd-migration.sh` - Move Jellyfin to HDD

---

**Generated**: $(date)
**Status**: Ready for implementation
