#!/bin/bash
# Phase 03.5: GPU Operator with Time-Slicing
# Based on working old script logic

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

GPU_NAMESPACE="gpu-operator"
GPU_OPERATOR_VERSION="v25.3.4"
GPU_TS_REPLICAS="${GPU_TIMESLICING_REPLICAS:-2}"

check_nfd_running() {
    log "Checking if Node Feature Discovery (NFD) is already running..."
    local nfd_exists
    nfd_exists=$(kubectl get nodes -o json | jq '.items[].metadata.labels | keys | any(startswith("feature.node.kubernetes.io"))' 2>/dev/null || echo "false")
    
    if [ "$nfd_exists" = "true" ]; then
        log "NFD is already running in cluster"
        return 0
    else
        log "NFD not running, GPU Operator will deploy it"
        return 1
    fi
}

install_gpu_operator_with_timeslicing() {
    log "Installing NVIDIA GPU Operator with time-slicing..."
    
    # Add NVIDIA Helm repo
    helm repo add nvidia https://helm.ngc.nvidia.com/nvidia 2>/dev/null || true
    helm repo update
    
    # Create namespace
    kubectl create namespace "$GPU_NAMESPACE" 2>/dev/null || true
    kubectl label --overwrite namespace "$GPU_NAMESPACE" pod-security.kubernetes.io/enforce=privileged
    
    # Check NFD status
    local nfd_flag=""
    if check_nfd_running; then
        nfd_flag="--set nfd.enabled=false"
        log "Disabling NFD in GPU Operator (already running)"
    fi
    
    # Install with time-slicing configured at installation time
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
    
    success "GPU Operator installed"
}

apply_timeslicing_config() {
    log "Applying time-slicing configuration..."
    
    # Create ConfigMap BEFORE or during operator installation
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
    
    success "Time-slicing config applied (${GPU_TS_REPLICAS} replicas per GPU)"
}

wait_for_gpu_operator() {
    log "Waiting for GPU Operator components..."
    
    # Wait for driver
    kubectl wait --for=condition=ready pods \
        --selector=app=nvidia-driver-daemonset \
        --namespace="$GPU_NAMESPACE" \
        --timeout=600s || warn "Driver pods timeout"
    
    # Wait for device plugin
    kubectl wait --for=condition=ready pods \
        --selector=app=nvidia-device-plugin-daemonset \
        --namespace="$GPU_NAMESPACE" \
        --timeout=300s || warn "Device plugin timeout"
    
    success "GPU Operator components ready"
}

verify_gpu_capacity() {
    log "Verifying GPU capacity with time-slicing..."
    sleep 20
    
    local gpu_count
    gpu_count=$(kubectl get nodes -o json | jq -r '.items[].status.capacity."nvidia.com/gpu"' | head -1)
    
    if [ -n "$gpu_count" ] && [ "$gpu_count" != "null" ]; then
        success "GPU capacity detected: ${gpu_count} logical GPUs"
        log "Expected: ${GPU_TS_REPLICAS} per physical GPU"
    else
        warn "GPU capacity not yet visible"
    fi
}

main() {
    log "Starting GPU Operator with Time-Slicing installation..."
    
    # Skip if no GPU
    if [ "${GPU_AVAILABLE:-false}" != "true" ]; then
        log "No GPU detected in system, skipping GPU Operator"
        return 0
    fi
    
    verify_command kubectl "kubectl required"
    verify_command helm "helm required"
    
    # Apply time-slicing config first
    apply_timeslicing_config
    
    # Install GPU Operator with time-slicing
    install_gpu_operator_with_timeslicing
    
    # Wait for components
    wait_for_gpu_operator
    
    # Verify
    verify_gpu_capacity
    
    success "GPU Operator with time-slicing configured"
}

main "$@"