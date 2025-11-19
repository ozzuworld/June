# Kubernetes Media Stack Architecture Analysis & Stability Report

## Executive Summary

This comprehensive analysis of the June platform Kubernetes deployment reveals a multi-namespace architecture with significant media processing capabilities. The system includes two main platforms (June Platform core services and June Dark OSINT framework) with integrated media stack (Jellyfin, video services) and WebRTC infrastructure (LiveKit, STUNner).

**Overall Stability Risk: MEDIUM-HIGH**
- Critical issues with resource allocation and health checks
- Database connection pooling not explicitly configured
- Memory-intensive media services without proper safeguards
- Missing pod disruption budgets and autoscaling policies

---

## 1. KUBERNETES CONFIGURATION OVERVIEW

### 1.1 Namespace Structure

```
┌─────────────────────────────────────────────────────────────┐
│ Kubernetes Cluster                                          │
├─────────────────────────────────────────────────────────────┤
│ june-services          │ june-dark     │ media-stack │ stunner
│ (Core Platform)        │ (OSINT)       │ (Media)     │ (WebRTC)
├─────────────────────────────────────────────────────────────┤
│ - Orchestrator         │ - PostgreSQL  │ - LiveKit   │ - Gateway
│ - Keycloak (IDP)       │ - Elasticsearch
│ - PostgreSQL           │ - Redis       │ - Jellyfin  │
│ - Redis                │ - RabbitMQ    │ - Prowlarr  │
│ - (STT/TTS optional)   │ - Neo4j       │ - Sonarr    │
│                        │ - MinIO       │ - Radarr    │
│                        │ - Kibana      │ - Lidarr    │
│                        │ - Collector   │ - qBittorrent
│                        │ - Enricher    │ - Jellyseerr
│                        │ - Orchestrator│
│                        │ - OpenCTI Con │
│                        │ - Ops-UI      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Storage Configuration

**File**: `/home/user/June/k8s/storage-classes.yaml`

Storage Classes Defined:
- `fast-ssd` (default): For databases, Redis, critical data
- `slow-hdd`: For media files, logs, backups
- `local-storage`: Legacy compatibility

**Issue**: All PVCs in `june-dark` have empty `storageClassName: ""` - they won't bind to the declared storage classes!

```yaml
# PROBLEMATIC CONFIGURATION
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi
  storageClassName: ""  # ❌ SHOULD BE "fast-ssd" or "slow-hdd"
```

---

## 2. RESOURCE ALLOCATION ANALYSIS

### 2.1 June Services Namespace

**File**: `/home/user/June/helm/june-platform/values.yaml`

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit | GPU |
|-----------|-------------|-----------|----------------|--------------|-----|
| Orchestrator | 200m | 500m | 512Mi | 1Gi | No |
| PostgreSQL | 100m | 500m | 256Mi | 512Mi | No |
| June-STS (if enabled) | 1000m | 2000m | 6Gi | 6Gi | 1x |
| June-TTS (if enabled) | 1000m | 2000m | 4Gi | 6Gi | 1x |
| Keycloak (IDP) | Not set | Not set | Not set | Not set | No |

**Critical Issue #1**: Keycloak has NO resource limits defined!
- Can consume unlimited CPU and memory
- Will cause cluster-wide resource contention
- No restart on OOMKill

### 2.2 June Dark OSINT Platform

**File**: `/home/user/June/k8s/june-dark/` (multiple manifests)

#### Total Resource Requirements (June Dark):

| Component | CPU Req | CPU Limit | Memory Req | Memory Limit | Notes |
|-----------|---------|-----------|-----------|--------------|-------|
| PostgreSQL | 500m | 2000m | 2Gi | 4Gi | max_connections=200 |
| Elasticsearch | 1000m | 2000m | 4Gi | 6Gi | Reduced from 8Gi |
| Neo4j | 500m | 1000m | 2Gi | 3Gi | Reduced from 4Gi |
| Redis | 100m | 500m | 512Mi | 1Gi | maxmemory=1gb |
| RabbitMQ | 200m | 1000m | 1Gi | 2Gi | Long startup time |
| MinIO | 200m | 500m | 512Mi | 1Gi | Storage backend |
| Orchestrator | 200m | 500m | 512Mi | 1Gi | |
| Collector (x2) | 200m | 500m | 512Mi | 1Gi | Concurrent=8 |
| Enricher (x2) | 200m | 500m | 512Mi | 1Gi | Batch size=10 |
| OpenCTI Connector | 100m | 500m | 256Mi | 512Mi | |
| Kibana | 200m | 1000m | 512Mi | 1Gi | |
| Ops-UI | 100m | 500m | 256Mi | 512Mi | |
| **TOTAL** | **3.7 cores** | **10.5 cores** | **15.5Gi** | **27Gi** | |

**Critical Issue #2**: This configuration requires:
- Minimum 4 CPU cores just for requests (not counting June platform)
- 15.5Gi RAM minimum for basic operation
- Total limit headroom of 10.5 cores + 27Gi possible usage

### 2.3 Media Stack (Not fully deployed)

Not scheduled in K8s by default - deployed via separate installation scripts. Would add:
- Jellyfin: 100-1000m CPU, 512Mi-2Gi memory
- Prowlarr: 50-250m CPU, 128-256Mi memory
- Sonarr: 50-500m CPU, 256-512Mi memory
- Radarr: 50-500m CPU, 256-512Mi memory
- Lidarr: 50-500m CPU, 256-512Mi memory
- qBittorrent: 100-1000m CPU, 256Mi-1Gi memory
- Jellyseerr: 50-250m CPU, 128-256Mi memory

---

## 3. HEALTH PROBES & STARTUP CHECKS

### 3.1 Liveness & Readiness Probes Inventory

**Deployments WITH proper health checks** (11 total):

✅ June Orchestrator (Helm):
- Readiness: HTTP GET /healthz (port 8080, 10s initial delay, 10s period)
- Liveness: HTTP GET /healthz (port 8080, 30s initial delay, 15s period)

✅ PostgreSQL (Helm):
- Readiness: exec `pg_isready -U keycloak` (5s initial, 5s period)
- Liveness: exec `pg_isready -U keycloak` (30s initial, 10s period)

✅ PostgreSQL (june-dark):
- Readiness: exec `pg_isready -U juneadmin` (10s initial, 5s period)
- Liveness: exec `pg_isready -U juneadmin` (30s initial, 10s period)

✅ Redis:
- Readiness: exec `redis-cli ping` (5s initial, 5s period)
- Liveness: exec `redis-cli ping` (10s initial, 10s period)

✅ RabbitMQ:
- Readiness: exec `rabbitmq-diagnostics check_running` (30s initial, 10s period)
- Liveness: exec `rabbitmq-diagnostics ping` (90s initial, 30s period, 5s timeout)
  - Note: 90s startup + 30s period = possible 2+ minute detection of failures

✅ Elasticsearch:
- Readiness: HTTP GET /_cluster/health (port 9200, 60s initial, 10s period)
- Liveness: HTTP GET /_cluster/health (port 9200, 90s initial, 30s period)

✅ Neo4j:
- Readiness: HTTP GET / (port 7474, 60s initial, 10s period)
- Liveness: HTTP GET / (port 7474, 90s initial, 30s period)

✅ MinIO:
- Readiness: HTTP GET /minio/health/ready (10s initial, 10s period)
- Liveness: HTTP GET /minio/health/live (30s initial, 20s period)

✅ Kibana:
- Readiness: HTTP GET /api/status (60s initial, 10s period)
- Liveness: HTTP GET /api/status (120s initial, 30s period)

✅ Orchestrator/Enricher/Collector/OpenCTI (june-dark):
- Readiness: HTTP GET /health (port 8080/9010, 30s-60s initial, 10s period)
- Liveness: HTTP GET /health (port 8080/9010, 60s-90s initial, 30s period)

✅ Keycloak (IDP, Helm):
- Readiness: HTTP GET /health/ready (port 9000, 60s initial, 10s period)
- Liveness: HTTP GET /health/live (port 9000, 90s initial, 20s period)

❌ **MISSING/INADEQUATE HEALTH CHECKS**:

- **TTS Service** (June Helm): No health checks defined!
- **STT Service** (June Helm): No health checks defined!
- **Virtual Kubelet (Vast GPU)**: Has startup probe, but unreliable for external provider
- **Keycloak (no resource limits)**: Will OOMKill with no graceful termination

### 3.2 Startup Issues

**Critical Issues Found**:

1. **RabbitMQ Long Startup** (90s initial delay)
   - Application takes ~13s to start
   - 90s initial delay gives 77s buffer
   - But with 30s failure period, total detection time = 120s (2 minutes)
   - Any cascade failures during startup will go undetected

2. **Elasticsearch Startup** (90s initial delay)
   - vm.max_map_count must be set via initContainer
   - sysctl -w vm.max_map_count=262144 may fail on restricted nodes

3. **TTS/STT Services Missing**
   - No health checks defined
   - TTS model loading takes 300s (5 minutes) for XTTS v2
   - No startup probe to account for this

---

## 4. MEDIA STACK COMPONENTS

### 4.1 TTS Service (Text-to-Speech)

**File**: `/home/user/June/June/services/june-tts/`

**Dockerfile**: CUDA 12.1 + PyTorch 2.4.0 + Coqui XTTS v2

Key Configuration:
```python
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
WARMUP_ON_STARTUP = 0  # Don't warmup (saves 3-5 minutes)
USE_DEEPSPEED = 0  # Optional performance enhancement
XTTS_SAMPLE_RATE = 24000  # Native XTTS
```

**Dependencies**:
- PyTorch 2.4.0 (torch, torchvision, torchaudio)
- Coqui TTS (XTTS v2)
- DeepSpeed (optional)
- asyncpg (PostgreSQL async client)
- FastAPI + Uvicorn

**Critical Issues**:

1. **Model Loading Delay**: 300s (5 minutes)
   - No health check to handle this
   - Pod will be marked as "running" before model loads
   - Requests will fail with 503s for first 5 minutes

2. **Voice Cache Management**:
   ```python
   voice_cache: Dict[str, Tuple[torch.Tensor, torch.Tensor]] = {}
   ```
   - In-memory unbounded cache
   - Each cached voice = ~200-500MB of GPU memory
   - Memory leak: no eviction policy!

3. **Database Connection**:
   ```python
   db_pool = None  # Global but not initialized
   ```
   - No connection pooling visible
   - `asyncpg` created fresh per request
   - Potential connection exhaustion

4. **GPU Memory Allocation**:
   ```python
   ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,expandable_segments:True
   ```
   - Expandable segments can cause fragmentation
   - No OOM protection

### 4.2 STT Service (Speech-to-Text)

**File**: `/home/user/June/June/services/june-stt/`

**Dockerfile**: CUDA 12.3.2 + cuDNN9 + Faster-Whisper

Key Configuration:
```python
compute_type: str = "int8_float16"  # Quantized inference
device: str = "auto"  # Auto-detect GPU
model: str = "large-v2"  # 1.5GB+ model
```

**Dependencies**:
- Faster-Whisper (optimized Whisper)
- whisper_streaming (online processing)
- PyTorch (torchaudio)
- FastAPI + WebSocket support
- LiveKit SDK

**Critical Issues**:

1. **Large Model Memory**:
   - large-v2 = 1.5GB+ on GPU
   - Quantization helps but still 600-800MB
   - No memory limits: can cause cluster OOMKill

2. **WebSocket Connection Management**:
   - Streaming audio processing
   - No connection timeout handling visible
   - Potential connection leak on client disconnect

3. **LiveKit Worker Integration**:
   - Background task for LiveKit room subscription
   - Runs during pod startup
   - If LiveKit unavailable, entire STT pod fails

### 4.3 Orchestrator Service

**File**: `/home/user/June/June/services/june-orchestrator/`

**Configuration Issues**:

1. **Database Connections**:
   ```python
   class RedisConfig:
       host: str = "redis.june-services.svc.cluster.local"
       port: int = 6379
       db: int = 1
       password: str = ""
   ```
   - Redis connections not pooled
   - Each request creates new connection in services

2. **HTTP Client Pooling Problem** ⚠️:
   ```python
   # Created fresh per request!
   async with httpx.AsyncClient(timeout=30.0) as client:
       response = await client.post(tts_url, json=payload)
   ```
   - Context manager creates/destroys pool every call
   - Should use module-level client for connection reuse
   - Can exceed max open files limit under load

3. **Memory Management**:
   - Session cleanup task (every 60 minutes)
   - In-memory conversation history
   - Dialogue state tracking: `short_term_memory`, `long_term_memory`, `semantic_memory`
   - No size limits on memory structures

4. **Configuration**:
   ```yaml
   max_conversation_length: 200  # Max turns
   max_history_messages: 20
   session_timeout_hours: 24
   cleanup_interval_minutes: 60
   max_context_tokens: 8000
   ```
   - Session timeout: 24 hours (can accumulate 576 sessions/day)
   - Cleanup every 60 minutes (could pause responsiveness)

---

## 5. DATABASE CONNECTIONS & POOLING

### 5.1 PostgreSQL Configuration

**Primary Database** (Helm): `/home/user/June/helm/june-platform/templates/postgresql.yaml`
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

**Secondary Database** (june-dark): `/home/user/June/k8s/june-dark/04-postgres.yaml`
```yaml
args:
  - "-c"
  - "max_connections=200"
  - "-c"
  - "shared_buffers=2GB"
  - "-c"
  - "effective_cache_size=6GB"
  - "-c"
  - "work_mem=16MB"
  - "-c"
  - "maintenance_work_mem=512MB"
```

**Issues**:
1. No explicit connection pooling at application level
2. max_connections=200 but no per-service limits
3. shared_buffers=2GB with only 4Gi limit = 50% of pod memory used by PostgreSQL alone
4. work_mem=16MB * 200 connections = potential 3.2GB overallocation

### 5.2 Application Connection Pooling

**June Dark ConfigMap** (CRITICAL):
```yaml
POSTGRES_POOL_SIZE: "20"
NEO4J_POOL_SIZE: "50"
REDIS_POOL_SIZE: "10"
```

**But these are not used**! Configuration shown in ConfigMap but not found in actual deployment code.

### 5.3 Redis Configuration

**Memory Management**:
```yaml
- --maxmemory
- "1gb"
- --maxmemory-policy
- allkeys-lru  # LRU eviction of all keys
```

**Good**: Bounded memory with LRU eviction
**Bad**: LRU eviction at 1GB could cause sudden data loss

---

## 6. MESSAGE QUEUES & EVENT PROCESSING

### 6.1 RabbitMQ Configuration

**File**: `/home/user/June/k8s/june-dark/06-redis-rabbitmq.yaml`

```yaml
RABBITMQ_DEFAULT_USER: "juneadmin"
RABBITMQ_DEFAULT_PASS: "juneR@bbit2024"
```

**Resource Allocation**:
```yaml
requests:
  memory: "1Gi"
  cpu: "200m"
limits:
  memory: "2Gi"
  cpu: "1000m"
```

**Health Checks**:
```yaml
livenessProbe:
  exec:
    command:
      - rabbitmq-diagnostics
      - ping
  initialDelaySeconds: 90  # ⚠️ LONG STARTUP
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 5  # 5 * 30s = 2.5 minutes to declare dead
```

**Issues**:
1. 90-second startup grace period
2. 5 failure threshold = 150-second total delay before restart
3. No prefetch count limiting visible
4. No queue depth monitoring

### 6.2 Collector Service

Uses RabbitMQ with:
```yaml
CONCURRENT_REQUESTS: "8"
DOWNLOAD_DELAY: "1.0"  # Seconds between requests
```

**Issue**: Concurrent web scraping with 8 concurrent connections - potential for IP bans.

---

## 7. FILE STORAGE & VOLUMES

### 7.1 Persistent Volume Claims

**June-Dark PVCs**:

| PVC | Size | Storage Class | Issue |
|-----|------|---------------|-------|
| elasticsearch-pvc | 50Gi | "" | No SC binding |
| postgres-pvc | 20Gi | "" | No SC binding |
| neo4j-data-pvc | 30Gi | "" | No SC binding |
| minio-pvc | 100Gi | "" | No SC binding |
| redis-pvc | 5Gi | "" | No SC binding |
| rabbitmq-pvc | 10Gi | "" | No SC binding |

**Critical Issue**: All PVCs have empty `storageClassName: ""` 
- They cannot bind to fast-ssd or slow-hdd classes
- They'll attempt to use default class (fast-ssd) but may fail
- No local PVs provisioned = **Pods will stay Pending**

### 7.2 Media Stack Volumes

TTS/STT services use:
```yaml
emptyDir:
  sizeLimit: 10Gi  # Model cache
emptyDir:
  sizeLimit: 5Gi   # Temp cache
```

**Issue**: Node-local storage, lost on pod restart!

---

## 8. MONITORING & LOGGING

### 8.1 Observability Stack (June-Dark)

- **Elasticsearch**: 50Gi storage, 4-6Gi memory
- **Kibana**: Dashboard at port 5601
- **Logs**: Directed to Elasticsearch

**Missing**:
- No Prometheus for metrics
- No Grafana for visualization
- No AlertManager for alerts
- No log shipping to central location

### 8.2 Current Logging

All services use:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"  # Rotate after 3 files
```

**Issues**:
- Only 30MB total logs per service (10MB * 3 files)
- Old logs deleted automatically
- No centralized log analysis
- No structured logging for metrics

---

## 9. CRITICAL FINDINGS: POTENTIAL CLUSTER INSTABILITY CAUSES

### Priority 1: IMMEDIATE RISKS

#### 1.1 Keycloak Missing Resource Limits
**File**: `/home/user/June/helm/june-platform/templates/june-idp.yaml`

```yaml
# ❌ NO RESOURCE LIMITS!
containers:
  - name: keycloak
    image: docker.io/ozzuworld/june-idp:latest
    # resources: NOT DEFINED
```

**Impact**:
- Keycloak can consume all cluster memory
- Causes OOMKill of other pods
- No restart guarantee (kill is sudden)
- Entire cluster can become unstable

**Mitigation Required**:
```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "1000m"
```

#### 1.2 TTS/STT Missing Health Checks
**File**: `/home/user/June/helm/june-platform/templates/june-tts.yaml`

```yaml
# ❌ NO HEALTH CHECKS!
containers:
  - name: tts
    image: "..."
    # livenessProbe: NOT DEFINED
    # readinessProbe: NOT DEFINED
    # startupProbe: NOT DEFINED
```

**Impact**:
- TTS marked "ready" but model still loading (5 minutes)
- Requests fail for first 5 minutes
- Pod stuck in Failed state not restarted

**Mitigation Required**:
```yaml
startupProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 60  # 300 seconds total

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 310  # After model load
  periodSeconds: 10

livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 310
  periodSeconds: 30
  failureThreshold: 3
```

#### 1.3 Connection Pooling Not Implemented
**Multiple services** creating new HTTP clients per request

```python
# BAD - in orchestrator/services/tts_service.py
async def synthesize(text):
    async with httpx.AsyncClient(timeout=10.0) as client:  # NEW CONNECTION
        response = await client.post(tts_url, json=payload)
```

**Impact**:
- Connection exhaustion under load
- File descriptor limit reached
- OS kills process with "Too many open files"
- Service becomes unavailable

**Mitigation Required**:
```python
# Create once at module level
tts_client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=100))

# Reuse in functions
async def synthesize(text):
    response = await tts_client.post(tts_url, json=payload)
```

#### 1.4 PVC Storage Class Binding Issue
**All June-Dark PVCs** have empty storageClassName

**Impact**:
- PVCs stay in "Pending" state
- Pods dependent on PVCs cannot start
- June-Dark services completely non-functional

**Mitigation Required**:
```yaml
# For all PVCs, update to:
storageClassName: "fast-ssd"  # For databases
# OR
storageClassName: "slow-hdd"  # For bulk storage
```

### Priority 2: HIGH RISK (Stability Issues)

#### 2.1 Voice Cache Memory Leak (TTS)
**File**: `/home/user/June/June/services/june-tts/app/main.py`

```python
voice_cache: Dict[str, Tuple[torch.Tensor, torch.Tensor]] = {}

def get_conditioning_latents(voice_id):
    if voice_id not in voice_cache:
        # Load and cache forever
        gpt_cond_latent, speaker_embedding = ...
        voice_cache[voice_id] = (gpt_cond_latent, speaker_embedding)  # NO EVICTION
    return voice_cache[voice_id]
```

**Impact**:
- Each cached voice ≈ 200-500MB GPU memory
- 10 unique voices = 2-5GB GPU memory leak
- Service crashes with OOMKill after days of operation

**Mitigation Required**:
```python
from functools import lru_cache

@lru_cache(maxsize=10)  # Keep only 10 voices
def get_conditioning_latents(voice_id):
    ...
```

#### 2.2 RabbitMQ Slow Failure Detection
**File**: `/home/user/June/k8s/june-dark/06-redis-rabbitmq.yaml`

```yaml
livenessProbe:
  initialDelaySeconds: 90
  periodSeconds: 30
  failureThreshold: 5
```

**Impact**:
- Total time to detect failure = 90 + (30 * 5) = 240 seconds (4 minutes)
- Any RabbitMQ failure blocks all event processing for 4 minutes
- Dependent services (Collector, Enricher) hang

**Mitigation Required**:
```yaml
livenessProbe:
  initialDelaySeconds: 90
  periodSeconds: 10  # Reduce from 30
  failureThreshold: 3  # Reduce from 5 (total: 90 + 30 = 120s)
  timeoutSeconds: 5
```

#### 2.3 PostgreSQL shared_buffers Overallocation
**File**: `/home/user/June/k8s/june-dark/04-postgres.yaml`

```yaml
args:
  - "-c"
  - "shared_buffers=2GB"    # 50% of 4Gi limit!
  - "-c"
  - "effective_cache_size=6GB"  # More than pod can have!
  - "-c"
  - "work_mem=16MB"  # Times 200 connections = 3.2GB possible
```

**Impact**:
- shared_buffers=2GB uses half of pod memory limit
- work_mem=16MB * 200 connections = could request 3.2GB total
- Easy to OOMKill under concurrent load

**Mitigation Required**:
```yaml
args:
  - "-c"
  - "max_connections=100"  # Reduce from 200
  - "-c"
  - "shared_buffers=1GB"    # 25% of 4Gi limit
  - "-c"
  - "effective_cache_size=3GB"
  - "-c"
  - "work_mem=8MB"  # Times 100 = 800MB max
  - "-c"
  - "max_parallel_workers_per_gather=2"
```

#### 2.4 Elasticsearch Memory Configuration
**File**: `/home/user/June/k8s/june-dark/03-elasticsearch.yaml`

```yaml
env:
  - name: ES_JAVA_OPTS
    value: "-Xms2g -Xmx4g"  # 4GB HEAP
  - name: bootstrap.memory_lock
    value: "false"  # Disabled (good for K8s)
```

With 6Gi pod memory limit, this leaves only 2Gi for:
- JVM overhead (300-500MB)
- OS/buffer (500MB)
- Field data cache (500MB)
- Results cache (200MB)

**Impact**:
- Frequent GC pauses (seconds)
- High query latency
- Potential OOMKill

**Mitigation Required**:
- Reduce heap to `-Xms1g -Xmx3g` OR
- Increase pod memory limit to 8Gi

#### 2.5 RabbitMQ initContainer Privilege Escalation
**File**: `/home/user/June/k8s/june-dark/06-redis-rabbitmq.yaml`

```yaml
initContainers:
  - name: fix-permissions
    securityContext:
      runAsUser: 0  # Root!
    command:
      - sh
      - -c
      - |
        chown -R 999:999 /var/lib/rabbitmq
        # ...
```

**Impact**:
- Requires privileged pod (security hole)
- May fail in restricted namespaces
- Pod won't start in restricted environments

**Mitigation Required**:
- Pre-create volumes with correct ownership
- Or use fsGroup in pod securityContext

### Priority 3: MEDIUM RISK (Performance Issues)

#### 3.1 No Horizontal Pod Autoscaling (HPA)
**No HPA policies defined anywhere**

**Impact**:
- Fixed 2 replicas for Collector/Enricher
- Cannot scale under load
- Cannot scale down when idle (wasting resources)

**Mitigation Required**:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: collector-hpa
  namespace: june-dark
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: collector
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

#### 3.2 No Pod Disruption Budgets (PDB)
**No PDB policies defined**

**Impact**:
- Kubernetes maintenance can evict all instances
- Any pod can be suddenly killed
- Services become unavailable during cluster upgrades

**Mitigation Required**:
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-pdb
  namespace: june-dark
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: postgres
```

#### 3.3 Resource Quotas Not Enforced
**No ResourceQuota per namespace**

**Impact**:
- June-Dark can consume all cluster resources
- Blocks other namespaces from operating
- Noisy neighbor problem

**Mitigation Required**:
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: june-dark-quota
  namespace: june-dark
spec:
  hard:
    requests.cpu: "4"
    requests.memory: "16Gi"
    limits.cpu: "8"
    limits.memory: "32Gi"
    pods: "50"
```

#### 3.4 Missing Startup Probes for Long-Loading Services
**TTS Model Loading**: 300+ seconds
**Elasticsearch**: 60+ seconds

Without startup probes:
- Readiness probe fails during startup
- Service marked "not ready" for 5+ minutes
- Requests return 503 Service Unavailable

---

## 10. CI/CD PIPELINE ANALYSIS

**File**: `/home/user/June/.github/workflows/build-june-services.yml`

Current workflow:
- Manual dispatch trigger
- Builds Docker images
- Pushes to registry
- No automatic deployment

**Issues**:
- No automated testing before deployment
- No image scanning for vulnerabilities
- No rollback strategy defined
- Manual image pulling required

---

## 11. DEPLOYMENT CONFIGURATION ISSUES

### 11.1 Database Initialization

**Helm Wait Container** (june-idp.yaml):
```yaml
initContainers:
  - name: wait-for-postgres
    image: postgres:15-alpine
    command:
    - sh
    - -c
    - |
      until pg_isready -h postgresql.{{ .Release.Namespace }}.svc.cluster.local -p 5432 -U keycloak; do
        sleep 3
      done
```

**Issue**: Only checks if PostgreSQL is listening, not if database is ready for queries.

### 11.2 ConfigMap-Based Configuration
**Multiple services** rely on ConfigMaps for critical settings:

```yaml
data:
  ELASTIC_URL: "http://elasticsearch:9200"
  NEO4J_URI: "bolt://neo4j:7687"
  POSTGRES_DSN: "postgresql://juneadmin:juneP%40ssw0rd2024@postgres:5432/june_osint"
```

**Issues**:
- Passwords in ConfigMaps (should be Secrets)
- No validation of URLs
- Service updates require ConfigMap updates + pod restart

---

## 12. SUMMARY OF CRITICAL FINDINGS

### Immediate Actions Required

| Issue | Severity | Impact | Effort |
|-------|----------|--------|--------|
| Keycloak missing resource limits | P1 | Cluster instability | Low |
| TTS/STT missing health checks | P1 | Service unavailability | Low |
| Connection pooling not implemented | P1 | File descriptor exhaustion | Medium |
| PVC storage class binding issue | P1 | Pods won't start | Low |
| Voice cache memory leak | P2 | Memory exhaustion after days | Low |
| RabbitMQ slow failure detection | P2 | 4-minute service downtime | Low |
| PostgreSQL memory overallocation | P2 | Frequent OOMKill | Medium |
| Elasticsearch memory tuning | P2 | GC pauses, latency | Low |
| RabbitMQ privileged initContainer | P3 | Security issue | Medium |
| No HPA policies | P3 | Cannot scale | Medium |
| No PDB policies | P3 | Sudden evictions | Low |
| No ResourceQuotas | P3 | Resource contention | Low |

### Architecture Bottlenecks

1. **Single-point-of-failure databases** (no replication)
2. **No event queue depth monitoring** (RabbitMQ)
3. **No circuit breakers** for external service calls
4. **No request rate limiting** at ingress
5. **In-memory caches** without eviction policies
6. **Long startup times** without startup probes

---

## 13. RECOMMENDATIONS

### Short-term (1-2 weeks)
1. Add resource limits to Keycloak
2. Add health checks to TTS/STT
3. Implement connection pooling in services
4. Fix PVC storage class bindings
5. Add voice cache eviction (LRU)

### Medium-term (2-4 weeks)
1. Implement HPA for scalable services
2. Add PDB policies
3. Add ResourceQuotas
4. Implement circuit breakers
5. Add comprehensive monitoring (Prometheus + Grafana)

### Long-term (1-3 months)
1. Implement database replication
2. Add message queue monitoring
3. Implement service mesh (Istio/Linkerd)
4. Add distributed tracing
5. Implement automated scaling based on metrics

---

## Appendix A: File Location Reference

### Kubernetes Configuration Files

```
/home/user/June/
├── helm/june-platform/
│   ├── chart.yaml
│   ├── values.yaml                          # Main Helm values
│   ├── values-optimized.yaml                # Optimized values
│   └── templates/
│       ├── june-orchestrator.yaml           # ❌ TTS/STT missing health checks
│       ├── june-tts.yaml                    # ❌ No resources/health checks
│       ├── june-stt.yaml                    # ❌ No resources/health checks
│       ├── june-idp.yaml                    # ❌ No resource limits
│       ├── postgresql.yaml
│       ├── ingress.yaml
│       └── ...
├── k8s/
│   ├── storage-classes.yaml                 # Storage class definitions
│   ├── june-dark/
│   │   ├── 01-configmap.yaml               # Database config (passwords exposed)
│   │   ├── 02-storage.yaml                 # ❌ PVCs missing storageClassName
│   │   ├── 03-elasticsearch.yaml           # Reduced memory config
│   │   ├── 04-postgres.yaml                # ⚠️  Memory overallocation
│   │   ├── 05-neo4j.yaml
│   │   ├── 06-redis-rabbitmq.yaml          # ⚠️  Long startup times
│   │   ├── 07-minio.yaml
│   │   ├── 08-orchestrator.yaml
│   │   ├── 09-collector.yaml
│   │   ├── 10-enricher.yaml
│   │   ├── 11-ops-ui.yaml
│   │   ├── 12-opencti-connector.yaml
│   │   ├── 13-ingress.yaml
│   │   ├── 14-postgres-init.yaml
│   │   └── 15-kibana.yaml
│   ├── media-stack/
│   │   ├── 00-namespace.yaml
│   │   ├── 01-cert-sync-cronjob.yaml
│   │   └── 10-livekit-ingress.yaml
│   ├── vast-gpu/
│   │   ├── gpu-services-deployment.yaml    # GPU resource allocation
│   │   └── virtual-kubelet-deployment.yaml # Vast.ai integration
│   └── stunner/
│       └── (WebRTC gateway config)
└── docs/
    ├── RESOURCE-OPTIMIZATION.md             # Resource tuning guide
    └── MEDIA-STACK-AUDIT.md
```

### Service Source Code

```
/home/user/June/June/services/
├── june-orchestrator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── config.py                       # Service config
│   │   ├── main.py                         # ❌ No HTTP client pooling
│   │   ├── services/
│   │   │   ├── tts_service.py             # ❌ New httpx client per request
│   │   │   └── simple_assistant.py
│   │   └── routes/
│   │       ├── webhooks.py
│   │       ├── livekit_token.py
│   │       └── vpn.py
├── june-tts/
│   ├── Dockerfile                          # XTTS v2 + PyTorch
│   ├── requirements.txt
│   └── app/main.py                         # ❌ Voice cache memory leak
├── june-stt/
│   ├── Dockerfile                          # Faster-Whisper + CUDA
│   ├── requirements.txt
│   ├── main.py
│   └── livekit_worker.py
└── june-dark/
    └── ...
```

---

## Appendix B: Resource Allocation Summary Table

### Current Total Allocations (Requested)

| Namespace | CPU Requests | Memory Requests | Status |
|-----------|-------------|-----------------|--------|
| june-services | 1.2-2.2 cores* | 2-3Gi* | *Depends on STT/TTS enabled |
| june-dark | 3.7 cores | 15.5Gi | All deployed |
| media-stack | 1.3 cores | 3Gi | Not deployed in K8s |
| stunner | 0.5 cores | 0.5Gi | (estimated) |
| **TOTAL** | **6.7-7.7 cores** | **21-22Gi** | Requires 8+ core machine |

### Recommended Minimum Hardware

- **Master Node**: 4 CPU, 8Gi RAM
- **Worker Node(s)**: 8+ CPU, 32Gi RAM minimum
- **Storage**: 500GB+ for PVCs

---

## Appendix C: References

- Kubernetes Health Checks: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Resource Management: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- Pod Disruption Budgets: https://kubernetes.io/docs/tasks/run-application/configure-pdb/
- Storage Classes: https://kubernetes.io/docs/concepts/storage/storage-classes/
- Horizontal Pod Autoscaler: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/

