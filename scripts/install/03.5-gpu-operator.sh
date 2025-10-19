#!/bin/bash
# June Platform - Phase 03.5: NVIDIA GPU Operator and Time-Slicing
# Installs NVIDIA GPU Operator via Helm (driver+toolkit+device plugin) and configures time-slicing.

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

GPU_NAMESPACE="gpu-operator"
GPU_OPERATOR_VERSION="v25.3.4"
GPU_TS_REPLICAS="${GPU_TIMESLICING_REPLICAS:-2}"

ensure_namespace() {
  kubectl create namespace "$GPU_NAMESPACE" 2>/dev/null || true
  kubectl label --overwrite namespace "$GPU_NAMESPACE" pod-security.kubernetes.io/enforce=privileged || true
}

ensure_helm_repo() {
  if ! helm repo list 2>/dev/null | awk '{print $1}' | grep -qx "nvidia"; then
    helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
  fi
  helm repo update
}

nfd_is_running() {
  # Detect if Node Feature Discovery labels exist on any node
  kubectl get nodes -o json 2>/dev/null | jq '.items[].metadata.labels | keys | any(.[]; startswith("feature.node.kubernetes.io"))' -r 2>/dev/null | grep -q true
}

install_gpu_operator() {
  header "Installing NVIDIA GPU Operator"
  ensure_namespace
  ensure_helm_repo

  local nfd_flag=""
  if nfd_is_running; then
    warn "NFD detected in cluster; disabling NFD deployment in GPU Operator"
    nfd_flag="--set nfd.enabled=false"
  fi

  helm upgrade --install gpu-operator nvidia/gpu-operator \
    --namespace "$GPU_NAMESPACE" \
    --version="$GPU_OPERATOR_VERSION" \
    --wait \
    --set driver.enabled=true \
    --set toolkit.enabled=true \
    --set devicePlugin.enabled=true \
    --set dcgmExporter.enabled=true \
    --set gfd.enabled=true \
    --set migManager.enabled=true \
    --set nodeStatusExporter.enabled=true \
    --set gds.enabled=false \
    --set vfioManager.enabled=true \
    --set sandboxWorkloads.enabled=false \
    --set vgpuManager.enabled=false \
    --set vgpuDeviceManager.enabled=false \
    --set ccManager.enabled=false \
    $nfd_flag

  success "NVIDIA GPU Operator installed/updated"
}

wait_for_gpu_components() {
  subheader "Waiting for GPU Operator components"
  # Driver
  kubectl wait --for=condition=ready pods \
    --selector=app=nvidia-driver-daemonset \
    --namespace="$GPU_NAMESPACE" \
    --timeout=600s || warn "Driver pods not fully ready within timeout"

  # Device plugin
  kubectl wait --for=condition=ready pods \
    --selector=app=nvidia-device-plugin-daemonset \
    --namespace="$GPU_NAMESPACE" \
    --timeout=300s || warn "Device plugin pods not fully ready within timeout"

  # Container toolkit (daemonset name varies by version; attempt best-known label)
  kubectl wait --for=condition=ready pods \
    --selector=app=nvidia-container-toolkit-daemonset \
    --namespace="$GPU_NAMESPACE" \
    --timeout=300s || warn "Container toolkit pods not fully ready within timeout"

  success "Wait sequence completed"
}

apply_timeslicing_config() {
  header "Configuring GPU time-slicing (replicas=${GPU_TS_REPLICAS})"

  # Use device plugin configuration via GPU Operator namespace
  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing-config
  namespace: $GPU_NAMESPACE
  labels:
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
EOF

  # Patch operator values so device plugin uses this config map
  # Some operator versions support devicePlugin.config.name; attempt it safely.
  if helm get values gpu-operator -n "$GPU_NAMESPACE" >/dev/null 2>&1; then
    helm upgrade gpu-operator nvidia/gpu-operator \
      -n "$GPU_NAMESPACE" \
      --reuse-values \
      --set devicePlugin.config.name=time-slicing-config
  fi
  success "Time-slicing configuration applied"
}

verify_gpu_capacity() {
  subheader "Verifying GPU capacity"
  sleep 20
  kubectl get nodes -o json | jq -r '.items[] | select(.status.allocatable["nvidia.com/gpu"]) | (.metadata.name+": "+.status.allocatable["nvidia.com/gpu"])' || true
}

main() {
  header "GPU Operator + Time-Slicing"

  if [ "$EUID" -ne 0 ]; then
    error "This script must be run as root"
  fi

  verify_command kubectl "kubectl is required"
  verify_command helm "helm is required"
  if ! kubectl cluster-info &>/dev/null; then
    error "Kubernetes cluster must be running"
  fi

  # Install Operator stack (driver/toolkit/device plugin) via Helm
  install_gpu_operator
  wait_for_gpu_components

  # Apply time-slicing
  if [ "${GPU_TS_REPLICAS}" -gt 1 ] 2>/dev/null; then
    apply_timeslicing_config
  else
    warn "GPU_TIMESLICING_REPLICAS=${GPU_TS_REPLICAS}; skipping time-slicing config"
  fi

  verify_gpu_capacity
  success "GPU Operator configuration completed"
}

main "$@"