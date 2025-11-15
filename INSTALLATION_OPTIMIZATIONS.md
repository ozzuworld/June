# Installation Optimizations - Automatic on Fresh Machine

## What's Been Changed

Your June Platform installation (`install-orchestrator.sh`) now automatically includes resource optimizations for machines with:
- **8 GPU | 64GB RAM | 250GB SSD | 1TB HDD**

### ✅ Automatic Optimizations

When you run `sudo ./scripts/install-orchestrator.sh` on a fresh machine, it now:

1. **Disables june-stt and june-tts by default** (freed: 2-4 CPU + 10-12GB RAM)
2. **Creates optimized storage classes** (SSD vs HDD separation)
3. **Uses optimized resource limits** for Elasticsearch and Neo4j
4. **Automatically sets up proper directory structure**
5. **Deploys June Dark with OpenCTI integration**

---

## Changes to Installation Flow

### New Phase Added: `04.1-storage-setup`
**When**: Runs after K8s setup, before services deployment
**What it does**:
- Creates `/mnt/ssd/` directory structure (250GB)
- Creates `/mnt/hdd/` directory structure (1TB)
- Creates storage classes: `fast-ssd`, `slow-hdd`, `local-storage`

### New Phase Added: `07.2-june-dark-opencti`
**When**: Runs after OpenCTI deployment
**What it does**:
- Deploys June Dark OSINT Framework
- Automatically integrates with OpenCTI
- Uses optimized resource configs

### Updated Installation Order
```
01. prerequisites
02. docker
03. kubernetes
04. infrastructure
04.1 storage-setup        ← NEW (creates /mnt/ssd, /mnt/hdd, storage classes)
05. helm
...
07.1 opencti
07.2 june-dark-opencti    ← NEW (deploys June Dark with optimizations)
08. livekit
09. june-platform         ← Uses optimized values.yaml
10. final-setup
```

---

## Default Configuration Changes

### 1. Helm Values (`helm/june-platform/values.yaml`)

**Before**:
```yaml
stt:
  enabled: true  # Consuming 1-2 CPU + 6GB RAM
tts:
  enabled: true  # Consuming 1-2 CPU + 4-6GB RAM

postgresql:
  storageClass: local-storage
  hostPath: /opt/june-postgresql-data
```

**After** (Optimized):
```yaml
stt:
  enabled: false  # ✅ Disabled - deploy separately on GPU instance
tts:
  enabled: false  # ✅ Disabled - deploy separately on GPU instance

postgresql:
  storageClass: fast-ssd  # ✅ SSD for performance
  hostPath: /mnt/ssd/postgresql
```

### 2. Elasticsearch Config (`k8s/june-dark/03-elasticsearch.yaml`)

**Before**:
```yaml
ES_JAVA_OPTS: "-Xms8g -Xmx8g"
resources:
  requests:
    memory: 10Gi
    cpu: 2000m
  limits:
    memory: 16Gi
    cpu: 4000m
```

**After** (Optimized - NOW DEFAULT):
```yaml
ES_JAVA_OPTS: "-Xms2g -Xmx4g"
resources:
  requests:
    memory: 4Gi   # ✅ Reduced from 10Gi
    cpu: 1000m    # ✅ Reduced from 2000m
  limits:
    memory: 6Gi   # ✅ Reduced from 16Gi
    cpu: 2000m    # ✅ Reduced from 4000m
```

### 3. Neo4j Config (`k8s/june-dark/05-neo4j.yaml`)

**Before**:
```yaml
NEO4J_server_memory_heap_initial__size: 2g
NEO4J_server_memory_heap_max__size: 4g
resources:
  requests:
    memory: 4Gi
    cpu: 1000m
  limits:
    memory: 8Gi
    cpu: 2000m
```

**After** (Optimized - NOW DEFAULT):
```yaml
NEO4J_server_memory_heap_initial__size: 1g
NEO4J_server_memory_heap_max__size: 2g
resources:
  requests:
    memory: 2Gi   # ✅ Reduced from 4Gi
    cpu: 500m     # ✅ Reduced from 1000m
  limits:
    memory: 3Gi   # ✅ Reduced from 8Gi
    cpu: 1000m    # ✅ Reduced from 2000m
```

---

## Storage Allocation (Automatic)

### SSD (250GB) - `/mnt/ssd/`
```
postgresql/      20GB
elasticsearch/   50GB
neo4j/          30GB
redis/           5GB
rabbitmq/       10GB
opensearch/     ~50GB (OpenCTI)
---
Used: ~165GB / 250GB (66%)
Free: ~85GB
```

### HDD (1TB) - `/mnt/hdd/`
```
jellyfin-media/    ~500GB (movies, TV)
minio-artifacts/    100GB (june-dark data)
backups/           ~100GB
logs/              ~50GB
---
Used: ~750GB / 1TB (75%)
Free: ~250GB
```

---

## Resource Usage After Optimization

### Before (Old Install)
```
june-stt:     1-2 CPU + 6GB RAM     ❌ Pending
june-tts:     1-2 CPU + 4-6GB RAM   ❌ Pending
elasticsearch: 2-4 CPU + 10-16GB    ❌ Too much
neo4j:        1-2 CPU + 4-8GB       ❌ Too much
---
TOTAL: 8-10 CPU + 35-40GB RAM       ❌ EXCEEDED
```

### After (New Install - Optimized)
```
june-stt:     DISABLED               ✅ 0 CPU + 0 RAM
june-tts:     DISABLED               ✅ 0 CPU + 0 RAM
elasticsearch: 1-2 CPU + 4-6GB       ✅ Optimized
neo4j:        0.5-1 CPU + 2-3GB      ✅ Optimized
---
TOTAL: 4-6 CPU + 25-32GB RAM        ✅ Within limits
```

**Freed**: 2-4 CPU cores + 10-15GB RAM ✅

---

## How to Deploy on Fresh Machine

### Standard Installation (Recommended)

```bash
cd /home/user/June

# 1. Configure
cp config.env.example config.env
nano config.env  # Set DOMAIN, API keys, etc.

# 2. Run full installation (includes all optimizations)
sudo ./scripts/install-orchestrator.sh
```

**What happens automatically**:
1. ✅ Installs prerequisites, Docker, K8s
2. ✅ **Creates optimized storage** (`04.1-storage-setup`)
3. ✅ Deploys infrastructure with optimized configs
4. ✅ Deploys OpenCTI
5. ✅ **Deploys June Dark with OpenCTI integration** (`07.2-june-dark-opencti`)
6. ✅ Deploys media services
7. ✅ Deploys June Platform (stt/tts disabled by default)

### Skip Specific Phases

```bash
# Skip GPU if no GPU needed
sudo ./scripts/install-orchestrator.sh --skip 02.5-gpu 03.5-gpu-operator

# Skip media services
sudo ./scripts/install-orchestrator.sh --skip 08.5-jellyfin 08.6-prowlarr

# Skip June Dark if not needed
sudo ./scripts/install-orchestrator.sh --skip 07.2-june-dark-opencti
```

---

## Verification After Installation

### Check All Pods Running
```bash
kubectl get pods -n june-services
# Should all be Running (no Pending)

kubectl get pods -n june-dark
# Should all be Running (if june-dark phase ran)
```

### Check Storage Classes
```bash
kubectl get sc

# Should show:
# fast-ssd (default)
# slow-hdd
# local-storage
```

### Check Resource Usage
```bash
kubectl top nodes

# Should show:
# CPU: 50-60% usage
# Memory: 40-50% usage
```

### Check Storage Directories
```bash
ls -la /mnt/ssd/
ls -la /mnt/hdd/
```

---

## What If You Want june-stt/june-tts?

If you need STT/TTS enabled on THIS machine (not recommended):

1. **Edit values.yaml**:
```bash
nano helm/june-platform/values.yaml

# Change:
stt:
  enabled: true
tts:
  enabled: true
```

2. **Redeploy**:
```bash
helm upgrade june-platform ./helm/june-platform -n june-services
```

**Note**: This will consume an additional 2-4 CPU + 10-12GB RAM and may cause resource exhaustion.

---

## Backup Files

Original (non-optimized) configs saved as:
- `k8s/june-dark/03-elasticsearch-ORIGINAL.yaml.bak`
- `k8s/june-dark/05-neo4j-ORIGINAL.yaml.bak`
- `helm/june-platform/values-optimized.yaml` (reference)

To restore original:
```bash
cd k8s/june-dark
mv 03-elasticsearch-ORIGINAL.yaml.bak 03-elasticsearch.yaml
mv 05-neo4j-ORIGINAL.yaml.bak 05-neo4j.yaml
```

---

## Summary

✅ **Installation is now optimized by default**
✅ **No manual intervention needed**
✅ **june-stt and june-tts disabled** (deploy separately)
✅ **Optimized resource limits** for all services
✅ **Automatic storage class creation** (SSD/HDD)
✅ **June Dark + OpenCTI integration** included

Just run `sudo ./scripts/install-orchestrator.sh` on a fresh machine and you're done!

---

**Last Updated**: $(date)
**Optimized For**: 8 GPU | 64GB RAM | 250GB SSD | 1TB HDD
