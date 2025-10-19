#!/bin/bash
# June Platform - Phase 03: NVIDIA GPU Operator and Time-Slicing
# Installs NVIDIA GPU Operator and configures time-slicing so multiple pods can share one GPU.

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Defaults (can be overridden via environment or config.env)
GPU_NAMESPACE="nvidia-gpu-operator"
GPU_TS_PROFILE_NAME="geforce-rtx-4090"
GPU_TS_REPLICAS="${GPU_TIMESLICING_REPLICAS:-2}"

ensure_helm_repo() {
  local name="$1" url="$2"
  if ! helm repo list | awk '{print $1}' | grep -qx "$name"; then
    helm repo add "$name" "$url"
  fi
}

apply_timeslicing_configmap() {
  log "Applying NVIDIA time-slicing ConfigMap with replicas=${GPU_TS_REPLICAS} for profile ${GPU_TS_PROFILE_NAME}..."
  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing-config
  namespace: $GPU_NAMESPACE
  labels:
    nvidia.com/operator.version: v1
    nvidia.com/device-plugin.config: "true"
data:
  timeslicing.yaml: |
    version: v1
    flags:
      migStrategy: none
    sharing:
      timeSlicing:
        resources:
          - name: nvidia.com/gpu
            replicas: ${GPU_TS_REPLICAS}
            # optional: match label to limit to certain nodes
            # nodeSelector:
            #   nvidia.com/gpu.product: "${GPU_TS_PROFILE_NAME}"
EOF
}

install_gpu_operator() {
  log "Installing NVIDIA GPU Operator..."
  kubectl create namespace "$GPU_NAMESPACE" 2>/dev/null || true

  ensure_helm_repo nvidia https://nvidia.github.io/gpu-operator
  helm repo update

  # Install or upgrade GPU Operator and point device plugin to our time-slicing ConfigMap
  helm upgrade --install gpu-operator nvidia/gpu-operator \
    --namespace "$GPU_NAMESPACE" \
    --set toolkit.enabled=true \
    --set devicePlugin.enabled=true \
    --set devicePlugin.config.name=time-slicing-config \
    --set driver.enabled=false \
    --set mig.strategy=none \
    --wait --timeout 20m

  success "GPU Operator installed/updated"
}

wait_for_gpu_resources() {
  log "Waiting for GPU operator components and device plugin..."
  # Device plugin DaemonSet
  if kubectl -n "$GPU_NAMESPACE" get ds nvidia-device-plugin-daemonset &>/dev/null; then
    kubectl -n "$GPU_NAMESPACE" rollout status ds/nvidia-device-plugin-daemonset --timeout=5m
  else
    warn "nvidia-device-plugin-daemonset not found yet"
  end

  # Validate nodes expose nvidia.com/gpu allocatable
  log "Checking for advertised GPU resources..."
  sleep 10
  kubectl get nodes -o json | jq -r '.items[] | select(.status.allocatable["nvidia.com/gpu"]) | "\(.metadata.name): \(.status.allocatable["nvidia.com/gpu"])"' || true
}

verify_timeslicing_effective() {
  log "Verifying time-slicing is effective (replicas=${GPU_TS_REPLICAS})..."
  # The device plugin with timeslicing will advertise fractional capacity as multiple allocatable GPUs (still named nvidia.com/gpu)
  local nodes;
  nodes=$(kubectl get nodes -o json | jq -r '.items[] | select(.status.allocatable["nvidia.com/gpu"]) | .metadata.name')
  if [ -z "$nodes" ]; then
    warn "No nodes advertising nvidia.com/gpu yet. It may take some time or require a reboot."
    return 0
  fi
  for n in $nodes; do
    local cap;
    cap=$(kubectl get node "$n" -o json | jq -r '.status.allocatable["nvidia.com/gpu"]')
    log "Node $n reports allocatable nvidia.com/gpu: $cap"
  done
  success "Time-slicing configuration applied"
}

main() {
  header "GPU Operator + Time-Slicing"

  # Must be root to manage system services during install flow
  if [ "$EUID" -ne 0 ]; then
    error "This script must be run as root"
  fi

  # Ensure kubectl/helm
  verify_command kubectl "kubectl is required"
  verify_command helm "helm is required"

  # Ensure a GPU is present at all
  if ! lspci | grep -i nvidia | grep -qi vga; then
    warn "No NVIDIA GPU detected, skipping GPU Operator installation"
    return 0
  fi

  # Sanity: try nvidia-smi; if missing, ask user to run 02.5-gpu first
  if ! command -v nvidia-smi &>/dev/null; then
    warn "nvidia-smi not found. Please run phase 02.5-gpu (GPU driver/runtime) first. Skipping for now."
    return 0
  fi

  install_gpu_operator
  apply_timeslicing_configmap
  wait_for_gpu_resources
  verify_timeslicing_effective

  success "GPU Operator configuration completed"
}

main "$@"
