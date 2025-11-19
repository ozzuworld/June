# Monitoring Stack Storage Class Fix

## Problem

The monitoring stack installation fails with pods stuck in "Pending" state because the configured storage classes (`fast-ssd` and `slow-hdd`) don't exist in your cluster.

```
NAME                                                       READY   STATUS    RESTARTS   AGE
alertmanager-kube-prometheus-stack-alertmanager-0          0/2     Pending   0          14m
kube-prometheus-stack-grafana-558967796d-crbsz             0/3     Pending   0          14m
prometheus-kube-prometheus-stack-prometheus-0              0/2     Pending   0          14m
```

## Root Cause

The values.yaml file references storage classes that don't exist:
- Prometheus: `storageClassName: slow-hdd` (line 31)
- Grafana: `storageClassName: fast-ssd` (line 109)
- AlertManager: `storageClassName: fast-ssd` (line 264)

## Solution Options

### Option 1: Automated Fix (Recommended)

Run the automated fix script:

```bash
cd /home/kazuma.ozzu/June/scripts/install/monitoring
bash fix-storage-classes.sh
```

The script will:
1. Check available storage classes in your cluster
2. Offer to create `fast-ssd` and `slow-hdd` classes OR use existing ones
3. Update the values.yaml file
4. Clean up the failed installation
5. Reinstall with correct configuration

### Option 2: Manual Fix

#### Step 1: Check Available Storage Classes

```bash
kubectl get storageclasses
```

Look for one marked with `(default)`. Common names:
- `standard`
- `local-path`
- `gp2` (AWS)
- `pd-standard` (GCP)

#### Step 2: Update Values File

Edit the file:

```bash
vim /home/kazuma.ozzu/June/k8s/monitoring/prometheus/values.yaml
```

Replace all occurrences of `slow-hdd` and `fast-ssd` with your actual storage class:

```yaml
# Line 31 - Prometheus
storageClassName: standard  # Change from slow-hdd

# Line 109 - Grafana
storageClassName: standard  # Change from fast-ssd

# Line 264 - AlertManager
storageClassName: standard  # Change from fast-ssd
```

#### Step 3: Clean Up Failed Installation

```bash
# Remove the failed Helm release
helm uninstall kube-prometheus-stack -n monitoring

# Delete stuck PVCs
kubectl delete pvc -n monitoring --all

# Wait for cleanup
sleep 10
```

#### Step 4: Reinstall

```bash
cd /home/kazuma.ozzu/June/scripts/install/monitoring
bash install-observability-stack.sh
```

### Option 3: Create Custom Storage Classes

If you want to keep the `fast-ssd` and `slow-hdd` names, create them:

#### For Local-Path Provisioner

```bash
# Create fast-ssd storage class
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
EOF

# Create slow-hdd storage class
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
EOF
```

Then restart the installation:

```bash
cd /home/kazuma.ozzu/June/scripts/install/monitoring
bash install-observability-stack.sh
```

#### For Cloud Providers

**AWS EKS:**

```yaml
# fast-ssd (gp3 SSD)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete

---
# slow-hdd (st1 HDD)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: ebs.csi.aws.com
parameters:
  type: st1
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
```

**GCP GKE:**

```yaml
# fast-ssd (pd-ssd)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-ssd
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete

---
# slow-hdd (pd-standard)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-standard
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
```

## Verification

After fixing and reinstalling:

### 1. Check Storage Classes

```bash
kubectl get storageclasses
```

Should show your configured classes.

### 2. Check PVCs

```bash
kubectl get pvc -n monitoring
```

Expected output (all should be "Bound"):

```
NAME                                               STATUS   VOLUME     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
alertmanager-kube-prometheus-stack-alertmanager-0  Bound    pvc-xxx    5Gi        RWO            standard       1m
kube-prometheus-stack-grafana                      Bound    pvc-xxx    5Gi        RWO            standard       1m
prometheus-kube-prometheus-stack-prometheus-0      Bound    pvc-xxx    50Gi       RWO            standard       1m
```

### 3. Check Pods

```bash
kubectl get pods -n monitoring
```

All pods should be "Running":

```
NAME                                                       READY   STATUS    RESTARTS   AGE
alertmanager-kube-prometheus-stack-alertmanager-0          2/2     Running   0          2m
kube-prometheus-stack-grafana-558967796d-crbsz             3/3     Running   0          2m
kube-prometheus-stack-operator-7b65886b7c-8s7xc            1/1     Running   0          2m
prometheus-kube-prometheus-stack-prometheus-0              2/2     Running   0          2m
```

### 4. Test Access

```bash
# Port-forward Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Open browser to http://localhost:3000
# Login: admin / CHANGE_ME_IMMEDIATELY
```

## Troubleshooting

### PVCs Still Pending

```bash
# Check PVC events
kubectl describe pvc -n monitoring <pvc-name>

# Common issues:
# - Storage class doesn't exist: Create it or use existing one
# - No provisioner: Install storage provisioner (local-path, CSI driver, etc.)
# - Insufficient resources: Free up disk space
```

### Pods Crash After Starting

```bash
# Check logs
kubectl logs -n monitoring <pod-name>

# Common issues:
# - Permission errors: Check pod security policies
# - Resource limits: Increase memory/CPU limits in values.yaml
```

### Helm Timeout

If installation times out but pods are starting:

```bash
# Check status
helm status kube-prometheus-stack -n monitoring

# Watch pods
watch kubectl get pods -n monitoring

# If pods eventually become Ready, the installation succeeded
```

## Storage Requirements

Default storage sizes in values.yaml:

| Component     | Storage Class | Size  | Usage |
|--------------|---------------|-------|-------|
| Prometheus   | slow-hdd      | 50Gi  | Metrics data (15 days retention) |
| Grafana      | fast-ssd      | 5Gi   | Dashboards, configs |
| AlertManager | fast-ssd      | 5Gi   | Alert state |

**Total: ~60Gi**

Adjust sizes in `values.yaml` if needed:

```yaml
# Prometheus (line 35)
storage: 50Gi  # Reduce if needed

# Grafana (line 110)
size: 5Gi

# AlertManager (line 267)
storage: 5Gi
```

## Prevention

To avoid this issue in future deployments:

1. **Always check available storage classes** before deploying stateful workloads:
   ```bash
   kubectl get storageclasses
   ```

2. **Use a default storage class** or explicitly specify existing ones in values files

3. **Create standard storage classes** for your cluster that all applications can use

4. **Document your storage classes** in cluster setup guides

## References

- Script: `/home/kazuma.ozzu/June/scripts/install/monitoring/fix-storage-classes.sh`
- Values: `/home/kazuma.ozzu/June/k8s/monitoring/prometheus/values.yaml`
- Kubernetes Storage Classes: https://kubernetes.io/docs/concepts/storage/storage-classes/
