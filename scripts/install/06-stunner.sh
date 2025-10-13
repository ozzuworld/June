#!/bin/bash
# June Platform - Phase 6: STUNner Installation
# Installs STUNner WebRTC gateway with Gateway API

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname "$(dirname "$(dirname "$0")")")"}" 

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

install_gateway_api() {
    log "Installing Gateway API..."
    
    # Install Gateway API CRDs
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml > /dev/null 2>&1
    
    # Wait for Gateway API CRDs with timeout
    log "Waiting for Gateway API CRDs..."
    local timeout=120
    local counter=0
    
    while [ $counter -lt $timeout ]; do
        if kubectl get crd gatewayclasses.gateway.networking.k8s.io &>/dev/null && \
           kubectl get crd gateways.gateway.networking.k8s.io &>/dev/null && \
           kubectl get crd udproutes.gateway.networking.k8s.io &>/dev/null; then
            success "Gateway API CRDs ready"
            return 0
        fi
        if [ $((counter % 20)) -eq 0 ]; then
            log "Still waiting for Gateway API CRDs... ($counter/${timeout}s)"
        fi
        sleep 2
        counter=$((counter + 2))
    done
    
    error "Gateway API CRDs failed to become ready within timeout"
}

install_stunner() {
    log "Installing STUNner operator..."
    
    # Add STUNner Helm repo with retry logic
    log "Adding STUNner Helm repository..."
    local retries=3
    for i in $(seq 1 $retries); do
        if helm repo add stunner https://l7mp.io/stunner > /dev/null 2>&1; then
            break
        fi
        if [ $i -eq $retries ]; then
            error "Failed to add STUNner Helm repository after $retries attempts"
        fi
        log "Retrying Helm repo add (attempt $i/$retries)..."
        sleep 5
    done
    
    helm repo update > /dev/null 2>&1
    
    # Install STUNner operator
    log "Installing STUNner operator..."
    helm upgrade --install stunner stunner/stunner \
        --create-namespace \
        --namespace=stunner-system \
        --wait \
        --timeout=15m \
        --set image.tag=latest \
        --set logLevel=info > /dev/null 2>&1
    
    # Verify STUNner operator is ready
    log "Waiting for STUNner operator to be ready..."
    wait_for_deployment "stunner" "stunner-system" 300
    
    success "STUNner operator installed"
}

wait_for_stunner_crds() {
    log "Waiting for STUNner CRDs..."
    
    local timeout=120
    local counter=0
    
    while [ $counter -lt $timeout ]; do
        if kubectl get crd gatewayconfigs.stunner.l7mp.io &>/dev/null && \
           kubectl get crd dataplanes.stunner.l7mp.io &>/dev/null; then
            success "STUNner CRDs ready"
            return 0
        fi
        if [ $((counter % 20)) -eq 0 ]; then
            log "Still waiting for STUNner CRDs... ($counter/${timeout}s)"
        fi
        sleep 2
        counter=$((counter + 2))
    done
    
    warn "STUNner CRDs took longer than expected, checking operator status..."
    kubectl get pods -n stunner-system
    kubectl logs -n stunner-system deployment/stunner --tail=20 || true
}

apply_stunner_config() {
    log "Applying STUNner configuration..."
    
    local stunner_config_dir="${ROOT_DIR}/k8s/stunner"
    
    if [ ! -d "$stunner_config_dir" ]; then
        warn "STUNner configuration directory not found at $stunner_config_dir"
        return 0
    fi
    
    # Create namespaces first
    if [ -f "${stunner_config_dir}/00-namespaces.yaml" ]; then
        log "Creating STUNner namespaces..."
        kubectl apply -f "${stunner_config_dir}/00-namespaces.yaml" > /dev/null 2>&1
        kubectl wait --for=condition=Active --timeout=60s namespace/stunner > /dev/null 2>&1 || true
    fi
    
    # Create authentication secret
    log "Creating STUNner authentication secret..."
    kubectl create secret generic stunner-auth-secret \
        --from-literal=type=static \
        --from-literal=username="${TURN_USERNAME:-june-user}" \
        --from-literal=password="${STUNNER_PASSWORD:-Pokemon123!}" \
        --namespace=stunner \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Apply configurations in order
    local config_files=(
        "20-dataplane-hostnet.yaml"
        "30-gatewayconfig.yaml"
        "40-gatewayclass.yaml"
        "50-gateway.yaml"
    )
    
    for config_file in "${config_files[@]}"; do
        local file_path="${stunner_config_dir}/${config_file}"
        if [ -f "$file_path" ]; then
            log "Applying ${config_file}..."
            kubectl apply -f "$file_path" > /dev/null 2>&1
            sleep 5  # Allow time for resources to be processed
        else
            warn "Configuration file not found: $file_path"
        fi
    done
    
    # Wait for gateway class to be accepted
    if kubectl get gatewayclass stunner &>/dev/null; then
        log "Waiting for gateway class to be accepted..."
        kubectl wait --for=condition=Accepted --timeout=120s \
            gatewayclass/stunner > /dev/null 2>&1 || warn "Gateway class acceptance timeout"
    fi
    
    # Wait for gateway to be ready
    if kubectl get gateway stunner-gateway -n stunner &>/dev/null; then
        log "Waiting for STUNner gateway to be programmed..."
        kubectl wait --for=condition=Programmed --timeout=180s \
            gateway/stunner-gateway -n stunner > /dev/null 2>&1 || warn "Gateway programming timeout"
    fi
    
    success "STUNner configuration applied"
}

verify_stunner() {
    log "Verifying STUNner installation..."
    
    # Check STUNner operator
    verify_namespace "stunner-system"
    verify_k8s_resource "deployment" "stunner" "stunner-system"
    
    # Check STUNner namespace and gateway
    if kubectl get namespace stunner &>/dev/null; then
        verify_namespace "stunner"
        
        if kubectl get gateway stunner-gateway -n stunner &>/dev/null; then
            success "STUNner gateway created successfully"
            
            # Show gateway status
            log "STUNner gateway status:"
            kubectl get gateway stunner-gateway -n stunner -o wide
        else
            warn "STUNner gateway not found"
        fi
    else
        warn "STUNner namespace not found"
    fi
    
    success "STUNner verification completed"
}

# Main execution
main() {
    log "Starting STUNner installation phase..."
    
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
    
    install_gateway_api
    install_stunner
    wait_for_stunner_crds
    apply_stunner_config
    verify_stunner
    
    success "STUNner installation phase completed"
}

main "$@"