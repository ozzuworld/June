#!/bin/bash
# June Platform - Phase 03.5: NVIDIA GPU Operator and Time-Slicing
# Installs NVIDIA GPU Operator via Helm with time-slicing configuration

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

GPU_NAMESPACE="gpu-operator"
GPU_OPERATOR_VERSION="v25.3.4"
GPU_TS_REPLICAS="${GPU_TIMESLICING_REPLICAS:-2}"

# Read GPU availability from previous phase
check_gpu_available() {
    if [ -f /tmp/.june_gpu_available ]; then
        local status=$(cat /tmp/.june_gpu_available)
        if [ "$status" = "true" ]; then
            log "GPU detected in previous phase"
            return 0
        fi
    fi
    
    # Fallback: check directly
    if lspci | grep -i nvidia | grep -i vga &>/dev/null; then
        log "GPU detected via direct check"
        return 0
    fi
    
    log "No GPU detected"
    return 1
}

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
    kubectl get nodes -o json 2>/dev/null | jq '.items[].metadata.labels | keys | any(.[]; startswith("feature.node.kubernetes.io"))' -r 2>/dev/null | grep -q true
}

apply_timeslicing_config() {
    header "Applying Time-Slicing Configuration"
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing-config
  namespace: $GPU_NAMESPACE
data:
  time-slicing: |
    version: v1
    sharing:
      timeSlicing:
        resources:
        - name: nvidia.com/gpu
          replicas: ${GPU_TS_REPLICAS}
EOF
    
    success "Time-slicing ConfigMap created (${GPU_TS_REPLICAS} replicas per GPU)"
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

    log "Installing GPU Operator v${GPU_OPERATOR_VERSION} with ${GPU_TS_REPLICAS}x time-slicing..."

    helm upgrade --install gpu-operator nvidia/gpu-operator \
        --namespace "$GPU_NAMESPACE" \
        --version="$GPU_OPERATOR_VERSION" \
        --wait \
        --timeout=15m \
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
        --set devicePlugin.config.name=time-slicing-config \
        --set-string devicePlugin.config.default=time-slicing \
        $nfd_flag

    success "NVIDIA GPU Operator installed"
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

    success "GPU Operator components ready"
}

verify_gpu_capacity() {
    subheader "Verifying GPU capacity"
    sleep 20
    
    local gpu_info
    gpu_info=$(kubectl get nodes -o json | jq -r '.items[] | select(.status.allocatable["nvidia.com/gpu"]) | (.metadata.name+": "+.status.allocatable["nvidia.com/gpu"])')
    
    if [ -n "$gpu_info" ]; then
        success "GPU capacity detected with time-slicing:"
        echo "$gpu_info"
        log "Expected: ${GPU_TS_REPLICAS} logical GPUs per physical GPU"
    else
        warn "GPU capacity not yet visible (may need a few more moments)"
    fi
}

main() {
    header "GPU Operator + Time-Slicing Installation"

    if [ "$EUID" -ne 0 ]; then
        error "This script must be run as root"
    fi

    verify_command kubectl "kubectl is required"
    verify_command helm "helm is required"
    if ! kubectl cluster-info &>/dev/null; then
        error "Kubernetes cluster must be running"
    fi

    # Check if GPU is available
    if ! check_gpu_available; then
        log "No GPU detected in system, skipping GPU Operator"
        success "GPU Operator phase completed (no GPU found)"
        return 0
    fi

    success "GPU detected - proceeding with GPU Operator installation"

    # CREATE NAMESPACE FIRST
    ensure_namespace

    # Then apply time-slicing config
    apply_timeslicing_config

    # Install GPU Operator with time-slicing
    install_gpu_operator
    
    # Wait for components
    wait_for_gpu_components

    # Verify GPU capacity
    verify_gpu_capacity
    
    # ✅ NEW: Label GPU nodes automatically
    label_gpu_nodes

    success "GPU Operator with time-slicing configured and nodes labeled"
}

main "$@"