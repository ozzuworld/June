#!/bin/bash
# June Platform - Phase 7: LiveKit Installation
# Installs LiveKit WebRTC server

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

install_livekit() {
    log "Phase 7/9: Installing LiveKit..."
    
    # Create media namespace
    log "Creating media namespace..."
    kubectl create namespace media --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    kubectl wait --for=condition=Active --timeout=60s namespace/media > /dev/null 2>&1
    
    # Add LiveKit Helm repo with retry logic
    log "Adding LiveKit Helm repository..."
    local retries=3
    for i in $(seq 1 $retries); do
        if helm repo add livekit https://helm.livekit.io > /dev/null 2>&1; then
            break
        fi
        if [ $i -eq $retries ]; then
            error "Failed to add LiveKit Helm repository after $retries attempts"
        fi
        log "Retrying LiveKit Helm repo add (attempt $i/$retries)..."
        sleep 5
    done
    
    helm repo update > /dev/null 2>&1
    
    success "LiveKit Helm repository added"
}

deploy_livekit_server() {
    log "Deploying LiveKit server..."
    
    local values_file="${ROOT_DIR}/k8s/livekit/livekit-values.yaml"
    
    if [ -f "$values_file" ]; then
        log "Using custom values file: $values_file"
        helm upgrade --install livekit livekit/livekit-server \
            --namespace media \
            --values "$values_file" \
            --wait \
            --timeout=15m > /dev/null 2>&1
    else
        log "Using default values for LiveKit installation"
        helm upgrade --install livekit livekit/livekit-server \
            --namespace media \
            --set server.replicas=1 \
            --set server.resources.requests.cpu=100m \
            --set server.resources.requests.memory=128Mi \
            --wait \
            --timeout=15m > /dev/null 2>&1
    fi
    
    success "LiveKit server deployed"
}

wait_for_livekit() {
    log "Waiting for LiveKit to be ready..."
    
    # Wait for LiveKit deployment to be available
    wait_for_deployment "livekit" "media" 300
    
    success "LiveKit is ready"
}

apply_livekit_services() {
    log "Applying LiveKit additional services..."
    
    local livekit_config_dir="${ROOT_DIR}/k8s/livekit"
    
    if [ ! -d "$livekit_config_dir" ]; then
        warn "LiveKit configuration directory not found at $livekit_config_dir"
        return 0
    fi
    
    # Apply UDP service if it exists
    if [ -f "${livekit_config_dir}/livekit-udp-svc.yaml" ]; then
        log "Applying LiveKit UDP service..."
        kubectl apply -f "${livekit_config_dir}/livekit-udp-svc.yaml" > /dev/null 2>&1
        sleep 5
    fi
    
    success "LiveKit additional services applied"
}

setup_udproute() {
    log "Setting up UDPRoute for LiveKit..."
    
    local udproute_file="${ROOT_DIR}/k8s/stunner/60-udproute-livekit.yaml"
    
    if [ ! -f "$udproute_file" ]; then
        warn "UDPRoute configuration not found at $udproute_file"
        return 0
    fi
    
    # Verify STUNner gateway exists first
    if ! kubectl get gateway stunner-gateway -n stunner &>/dev/null; then
        warn "STUNner gateway not found, skipping UDPRoute creation"
        return 0
    fi
    
    log "Applying UDPRoute for LiveKit..."
    kubectl apply -f "$udproute_file" > /dev/null 2>&1
    
    success "UDPRoute applied successfully"
}

setup_reference_grant() {
    log "Setting up ReferenceGrant for cross-namespace access..."
    
    # Create ReferenceGrant to allow STUNner to access LiveKit services
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-media
  namespace: media
spec:
  from:
  - group: stunner.l7mp.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF
    
    success "ReferenceGrant created"
}

verify_livekit() {
    log "Verifying LiveKit installation..."
    
    # Check LiveKit namespace and deployment
    verify_namespace "media"
    verify_k8s_resource "deployment" "livekit" "media"
    
    # Check if LiveKit service exists
    if kubectl get service livekit -n media &>/dev/null; then
        success "LiveKit service found"
    else
        warn "LiveKit service not found"
    fi
    
    # Show LiveKit status
    log "LiveKit status:"
    kubectl get pods -n media
    kubectl get services -n media
    
    success "LiveKit verification completed"
}

# Main execution
main() {
    log "Starting LiveKit installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify prerequisites
    verify_command "kubectl" "kubectl must be available"
    verify_command "helm" "helm must be available"
    
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster must be running"
    fi
    
    install_livekit
    deploy_livekit_server
    wait_for_livekit
    apply_livekit_services
    setup_udproute
    setup_reference_grant
    verify_livekit
    
    success "LiveKit installation phase completed"
}

main "$@"