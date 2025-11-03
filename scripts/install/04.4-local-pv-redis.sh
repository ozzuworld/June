#!/bin/bash
# June Platform - Phase 4.4: Local PVs for Redis
# Pre-create local PersistentVolumes so Bitnami Redis PVCs bind immediately

set -e

source "$(dirname "$0")/../common/logging.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

create_dirs() {
  for d in /opt/redis-data /opt/redis-replicas-data /opt/redis-replicas-1-data; do
    if [ ! -d "$d" ]; then
      mkdir -p "$d"
      chmod 755 "$d"
      log "Created directory $d"
    else
      log "Directory exists: $d"
    fi
  done
}

apply_pvs() {
  local host
  host=$(hostname)
  log "Applying local PVs bound to node: $host"

  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: redis-master-pv
spec:
  capacity:
    storage: 8Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  local:
    path: /opt/redis-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - ${host}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: redis-replicas-pv
spec:
  capacity:
    storage: 8Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  local:
    path: /opt/redis-replicas-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - ${host}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: redis-replicas-1-pv
spec:
  capacity:
    storage: 8Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  local:
    path: /opt/redis-replicas-1-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - ${host}
EOF
}

main() {
  log "Creating local directories for Redis PVs"
  create_dirs
  apply_pvs
  log "Local PVs for Redis applied"
}

main "$@"
