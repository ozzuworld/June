# Jellyfin Installation Fix Guide

## Problem Summary

The Jellyfin installation was failing with:
```
0/1 nodes are available: 1 node(s) didn't find available persistent volumes to bind
```

## Root Causes Identified

### 1. Path Inconsistency
- **04.1-storage-setup.sh** created directories at `/mnt/hdd/jellyfin-media` (on HDD)
- **08.5-jellyfin.sh** created directories at `/mnt/jellyfin/media` (unknown location)
- **Result**: Media storage wasn't on the 1TB HDD as intended

### 2. Missing PersistentVolume for Config
- Config PVC requested `storageClass: "fast-ssd"`
- The `fast-ssd` storage class uses `provisioner: kubernetes.io/no-provisioner`
- **No PV was created** for the config volume
- **Result**: Config PVC stuck in Pending state

### 3. Storage Class Mismatch
- Media PVC used empty storageClass `""`
- Should use `"slow-hdd"` to properly match the HDD-based PV
- **Result**: PVC binding issues

## What Was Fixed

### Scripts Updated

1. **scripts/install/04.1-storage-setup.sh**
   - Moved `jellyfin-config` from HDD to SSD (better performance)
   - Now creates: `/mnt/ssd/jellyfin-config` and `/mnt/hdd/jellyfin-media`

2. **scripts/install/08.5-jellyfin.sh**
   - Fixed directory paths to match storage setup
   - Created PV for both config AND media (was missing config PV)
   - Updated media PVC to use `slow-hdd` storageClass
   - Corrected all documentation strings

### Storage Layout (Corrected)

**SSD (250GB) - /mnt/ssd/**
- PostgreSQL, Redis, Elasticsearch, Neo4j, RabbitMQ, OpenSearch
- **Jellyfin Config** (5Gi) - Fast access for metadata/configuration

**HDD (1TB) - /mnt/hdd/**
- **Jellyfin Media** (500Gi) - Large storage for movies/TV shows
- MinIO artifacts, backups, logs

## How to Fix Your Existing Installation

### Step 1: Clean Up Failed Deployment

```bash
# Delete the failed Jellyfin deployment
kubectl delete deployment jellyfin -n june-services

# Delete the stuck PVCs
kubectl delete pvc jellyfin-config jellyfin-media -n june-services

# Delete any existing PVs
kubectl delete pv jellyfin-media-pv jellyfin-config-pv 2>/dev/null || true
```

### Step 2: Fix Directory Structure

```bash
# Create the correct directory structure
# SSD directories
mkdir -p /mnt/ssd/jellyfin-config
chown -R 1000:1000 /mnt/ssd/jellyfin-config
chmod -R 755 /mnt/ssd/jellyfin-config

# HDD directories
mkdir -p /mnt/hdd/jellyfin-media/{movies,tv,downloads/complete,downloads/incomplete}
chown -R 1000:1000 /mnt/hdd/jellyfin-media
chmod -R 755 /mnt/hdd/jellyfin-media

# Remove old incorrect directories if they exist
rm -rf /mnt/jellyfin 2>/dev/null || true
```

### Step 3: Verify Storage Classes Exist

```bash
# Check that storage classes are present
kubectl get storageclass

# You should see:
# fast-ssd (default)
# slow-hdd
# local-storage
```

If missing, create them:
```bash
kubectl apply -f /path/to/June/k8s/storage-classes.yaml
```

### Step 4: Re-run the Fixed Installation Script

```bash
cd /path/to/June
./scripts/install/08.5-jellyfin.sh
```

### Step 5: Verify Installation

```bash
# Check PVs are created and bound
kubectl get pv | grep jellyfin
# Should show:
# jellyfin-config-pv   5Gi     RWO   Retain   Bound    june-services/jellyfin-config   fast-ssd
# jellyfin-media-pv    500Gi   RWO   Retain   Bound    june-services/jellyfin-media    slow-hdd

# Check PVCs are bound
kubectl get pvc -n june-services | grep jellyfin
# Should show both as "Bound"

# Check pod is running
kubectl get pods -n june-services -l app.kubernetes.io/name=jellyfin
# Should show as "Running"

# Verify mounts inside container
kubectl exec -n june-services deployment/jellyfin -- df -h | grep -E '(config|media)'
```

## Verification Commands

```bash
# Check disk usage to confirm SSD vs HDD
df -h /mnt/ssd /mnt/hdd

# Verify directory ownership
ls -la /mnt/ssd/jellyfin-config
ls -la /mnt/hdd/jellyfin-media

# Watch pod startup
kubectl logs -n june-services -l app.kubernetes.io/name=jellyfin -f

# Check ingress
kubectl get ingress -n june-services | grep jellyfin
```

## Expected Result

After the fix:
- **Config PV**: 5Gi on SSD (`/mnt/ssd/jellyfin-config`) - fast metadata access
- **Media PV**: 500Gi on HDD (`/mnt/hdd/jellyfin-media`) - large media storage
- **Both PVCs**: Bound and ready
- **Pod**: Running successfully
- **Access**: https://tv.your-domain.com

## Future Prevention

The fixed scripts now:
1. Use consistent paths across all installation scripts
2. Create PVs for BOTH config and media (not just media)
3. Use correct storage classes (fast-ssd for config, slow-hdd for media)
4. Match the directory structure from 04.1-storage-setup.sh

## Questions or Issues?

If you still see binding issues:
1. Check that `/mnt/ssd` and `/mnt/hdd` actually exist and are on the right disks
2. Verify disk mounts: `lsblk` and `df -h`
3. Check node labels if using node affinity
4. Review PV/PVC events: `kubectl describe pvc jellyfin-config -n june-services`
