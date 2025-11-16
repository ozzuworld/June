# Kubernetes Resource Optimization Guide

## Problem

Your media stack pods are failing to schedule with:
```
FailedScheduling: 0/1 nodes are available: 1 Insufficient cpu
```

This means the cluster doesn't have enough CPU resources to schedule all requested workloads.

## Current Resource Requests

### Media Stack (scripts/install/08.*)

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|-------------|-----------|----------------|--------------|
| Jellyfin | 500m | 2000m (2 cores) | 1Gi | 4Gi |
| Prowlarr | 100m | 500m | 256Mi | 512Mi |
| Sonarr | 200m | 1000m (1 core) | 512Mi | 1Gi |
| Radarr | 200m | 1000m (1 core) | 512Mi | 1Gi |
| Jellyseerr | 100m | 500m | 256Mi | 512Mi |
| qBittorrent | 200m | 2000m (2 cores) | 512Mi | 2Gi |
| **TOTAL** | **1300m (1.3 cores)** | **7000m (7 cores)** | **3Gi** | **9Gi** |

### Understanding CPU Requests vs Limits

- **Requests**: Guaranteed resources. Kubernetes won't schedule the pod unless this much is available.
- **Limits**: Maximum burst capacity. Pod can use up to this much if available.

**The Problem**: Your cluster likely has 2-4 CPU cores total. The media stack alone requests 1.3 cores, and the June platform is already running (probably using 1-2 cores). This leaves insufficient CPU for new pods.

## Solution: Right-Size Resource Requests

These applications are **mostly idle** except during:
- Jellyfin: When streaming video (but transcoding is CPU-heavy)
- Prowlarr: When searching indexers (rare, bursty)
- Sonarr/Radarr: When searching and organizing (periodic, low CPU)
- Jellyseerr: When browsing UI (very light)
- qBittorrent: When downloading (I/O bound, not CPU bound)

### Optimized Resource Allocation

| Service | New CPU Request | New CPU Limit | New Mem Request | New Mem Limit | Rationale |
|---------|-----------------|---------------|-----------------|---------------|-----------|
| Jellyfin | 250m → **100m** | 2000m → **1000m** | 1Gi → **512Mi** | 4Gi → **2Gi** | Mostly idle, burst for transcoding |
| Prowlarr | 100m → **50m** | 500m → **250m** | 256Mi → **128Mi** | 512Mi → **256Mi** | Lightweight, periodic indexer queries |
| Sonarr | 200m → **50m** | 1000m → **500m** | 512Mi → **256Mi** | 1Gi → **512Mi** | Mostly idle, periodic scans |
| Radarr | 200m → **50m** | 1000m → **500m** | 512Mi → **256Mi** | 1Gi → **512Mi** | Mostly idle, periodic scans |
| Jellyseerr | 100m → **50m** | 500m → **250m** | 256Mi → **128Mi** | 512Mi → **256Mi** | Light web UI, mostly waiting |
| qBittorrent | 200m → **100m** | 2000m → **1000m** | 512Mi → **256Mi** | 2Gi → **1Gi** | I/O bound, CPU for hashing only |
| **NEW TOTAL** | **400m (0.4 cores)** | **3500m (3.5 cores)** | **1.3Gi** | **4.5Gi** |

**Savings**:
- CPU Requests: 1300m → 400m (69% reduction!)
- Memory Requests: 3Gi → 1.3Gi (57% reduction!)

## How to Apply

### Option 1: Run Diagnostic First (Recommended)

```bash
cd /path/to/June
./scripts/debug/check-cluster-resources.sh
```

This will show:
- Node capacity
- Current CPU/memory allocation
- Which pods are using the most resources
- Recommendations

### Option 2: Apply Optimized Configurations

I've created optimized installation scripts in `scripts/install-optimized/`:

```bash
# Stop existing media stack
kubectl delete deployment -n june-services jellyfin prowlarr sonarr radarr jellyseerr qbittorrent

# Re-deploy with optimized resources
./scripts/install-optimized/08.5-jellyfin.sh
./scripts/install-optimized/08.6-prowlarr.sh
./scripts/install-optimized/08.7-sonarr.sh
./scripts/install-optimized/08.8-radarr.sh
./scripts/install-optimized/08.9-jellyseerr.sh
./scripts/install-optimized/08.10-qbittorrent.sh
```

### Option 3: Manual Patch (Quick Fix)

Patch existing deployments:

```bash
# Jellyfin
kubectl set resources deployment jellyfin -n june-services \
  --requests=cpu=100m,memory=512Mi \
  --limits=cpu=1000m,memory=2Gi

# Prowlarr
kubectl set resources deployment prowlarr -n june-services \
  --requests=cpu=50m,memory=128Mi \
  --limits=cpu=250m,memory=256Mi

# Sonarr
kubectl set resources deployment sonarr -n june-services \
  --requests=cpu=50m,memory=256Mi \
  --limits=cpu=500m,memory=512Mi

# Radarr
kubectl set resources deployment radarr -n june-services \
  --requests=cpu=50m,memory=256Mi \
  --limits=cpu=500m,memory=512Mi

# Jellyseerr
kubectl set resources deployment jellyseerr -n june-services \
  --requests=cpu=50m,memory=128Mi \
  --limits=cpu=250m,memory=256Mi

# qBittorrent
kubectl set resources deployment qbittorrent -n june-services \
  --requests=cpu=100m,memory=256Mi \
  --limits=cpu=1000m,memory=1Gi
```

## Understanding Your Cluster Capacity

### Typical Single-Node Setups

| Node Type | CPU Cores | Usable CPU* | Memory | Recommended Max Requests |
|-----------|-----------|-------------|---------|--------------------------|
| Small VPS | 2 cores | ~1.6 cores | 4Gi | 1.2 cores, 3Gi |
| Medium VPS | 4 cores | ~3.6 cores | 8Gi | 2.8 cores, 6Gi |
| Large VPS | 8 cores | ~7.6 cores | 16Gi | 6 cores, 12Gi |
| Raspberry Pi 4 | 4 cores | ~3.8 cores | 4-8Gi | 3 cores, 3-6Gi |

*Usable = Total - system overhead (kubelet, OS, etc.)

### Current Recommendations

**For 2-core machine**: Use optimized configs (400m requests)
**For 4-core machine**: Use optimized configs (400m requests) or moderate configs (800m)
**For 8+ core machine**: Current configs are fine (1300m requests)

## Monitoring Resource Usage

### Install Metrics Server (if not installed)

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# If using self-signed certs, patch it:
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
```

### Check Actual Usage

```bash
# Node usage
kubectl top nodes

# Pod usage (sorted by CPU)
kubectl top pods --all-namespaces --sort-by=cpu

# Pod usage (sorted by memory)
kubectl top pods --all-namespaces --sort-by=memory
```

### Typical Actual Usage (Idle State)

| Service | Actual CPU (idle) | Actual Memory | Actual CPU (busy) |
|---------|-------------------|---------------|-------------------|
| Jellyfin | 10-20m | 300-500Mi | 100-800m (transcoding) |
| Prowlarr | 5-10m | 80-120Mi | 50-100m (searching) |
| Sonarr | 10-20m | 150-250Mi | 50-150m (scanning) |
| Radarr | 10-20m | 150-250Mi | 50-150m (scanning) |
| Jellyseerr | 5-10m | 80-150Mi | 20-50m (browsing) |
| qBittorrent | 10-30m | 100-200Mi | 50-200m (downloading) |

**Key Insight**: Even during "busy" periods, these apps rarely exceed 200m CPU (except Jellyfin transcoding). Our new requests of 50-100m provide plenty of headroom.

## Performance Impact

### Will Lower Requests Hurt Performance?

**No!** Here's why:

1. **Requests ≠ Performance**: Requests are scheduling guarantees, not performance limits
2. **Limits Control Performance**: The limits (250m-1000m) still allow burst capacity
3. **These Apps Are Bursty**: They sit idle 95% of the time, then burst briefly
4. **Quality of Service**: With requests set, they get guaranteed CPU during contention

### What If Multiple Apps Need CPU Simultaneously?

Kubernetes uses **CPU time slicing**:
- Each pod gets its requested CPU minimum
- Extra CPU is shared proportionally based on requests
- Limits prevent any pod from monopolizing CPU

**Example**: If Jellyfin is transcoding (500m actual) and Sonarr is scanning (100m actual):
- Total usage: 600m
- Both run smoothly if node has 1+ core available
- Limits prevent either from using all cores

## Troubleshooting

### Pods Still Pending After Optimization

```bash
# Check what's preventing scheduling
kubectl describe pod <pod-name> -n june-services

# Common issues:
# 1. PVC binding issues (see JELLYFIN-FIX-GUIDE.md)
# 2. Node has resource pressure (check: kubectl describe nodes)
# 3. Node is cordoned (check: kubectl get nodes)
```

### Pods OOMKilled (Out of Memory)

```bash
# Check actual memory usage
kubectl top pods -n june-services

# If a pod consistently hits its memory limit:
# Increase the memory limit (not request) for that specific pod
kubectl set resources deployment <name> -n june-services \
  --limits=memory=<new-limit>
```

### Performance Degradation

```bash
# Check if pods are being CPU throttled
kubectl top pods -n june-services

# If actual usage ≈ limit, increase limit:
kubectl set resources deployment <name> -n june-services \
  --limits=cpu=<new-limit>
```

## Best Practices

### 1. Start Conservative

Use optimized configs first. You can always increase later if needed.

### 2. Monitor Actual Usage

After deployment:
```bash
# Watch for a few days
watch kubectl top pods -n june-services
```

Adjust requests to be slightly above peak usage.

### 3. Separate Requests and Limits

- **Requests**: Set to typical usage (what you expect 90% of the time)
- **Limits**: Set to peak usage (what you might need during spikes)

**Example**:
```yaml
requests:
  cpu: 50m      # Normal: pod sits idle
  memory: 256Mi
limits:
  cpu: 500m     # Spike: user triggers library scan
  memory: 512Mi
```

### 4. Use HPA for Critical Services

For services that need to scale:
```bash
kubectl autoscale deployment jellyfin -n june-services \
  --cpu-percent=70 --min=1 --max=3
```

(Note: Requires metrics-server)

### 5. Node Anti-Affinity for Multi-Node

If you add nodes later:
```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchExpressions:
          - key: app
            operator: In
            values:
            - jellyfin
        topologyKey: kubernetes.io/hostname
```

## Quick Reference

### Resource Units

**CPU**:
- 1000m = 1 core
- 500m = 0.5 cores = 50% of 1 core
- 100m = 0.1 cores = 10% of 1 core

**Memory**:
- Ki = Kibibytes (1024 bytes)
- Mi = Mebibytes (1024 Ki)
- Gi = Gibibytes (1024 Mi)

### Common Values

| Usage Level | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-------------|-------------|-----------|----------------|--------------|
| Tiny | 25m | 100m | 64Mi | 128Mi |
| Small | 50m | 250m | 128Mi | 256Mi |
| Medium | 100m | 500m | 256Mi | 512Mi |
| Large | 250m | 1000m | 512Mi | 1Gi |
| XLarge | 500m | 2000m | 1Gi | 2Gi |

## Summary

✅ **Do This**:
1. Run diagnostic script to see current usage
2. Apply optimized configs (400m total requests)
3. Monitor for a few days
4. Adjust if needed

❌ **Don't Do This**:
1. Set requests = limits (wastes resources)
2. Over-provision requests (prevents scheduling)
3. Under-provision limits (causes throttling/OOM)
4. Ignore actual usage metrics

---

**Questions?** See the diagnostic script output or check actual pod usage with `kubectl top pods -n june-services`.
