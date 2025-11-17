#!/bin/bash
# WebRTC - STUNner Installation
# Installs STUNner WebRTC gateway with Gateway API

set -e

source "$(dirname "$0")/../../common/logging.sh"
source "$(dirname "$0")/../../common/validation.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

install_gateway_api() {
    log "Installing Gateway API with experimental features (for UDPRoute)..."
    
    if kubectl get crd gatewayclasses.gateway.networking.k8s.io &>/dev/null && \
       kubectl get crd udproutes.gateway.networking.k8s.io &>/dev/null; then
        success "Gateway API CRDs already installed"
        return 0
    fi
    
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml
    
    log "Waiting for Gateway API CRDs..."
    sleep 10
    
    success "Gateway API installed"
}

install_stunner() {
    log "Installing STUNner operator..."
    
    helm repo add stunner https://l7mp.io/stunner 2>/dev/null || true
    helm repo update
    
    helm upgrade --install stunner stunner/stunner \
        --create-namespace \
        --namespace=stunner-system \
        --wait \
        --timeout=15m \
        --set image.tag=latest \
        --set logLevel=info
    
    wait_for_deployment "stunner-gateway-operator-controller-manager" "stunner-system" 300
    
    success "STUNner operator installed"
}

apply_stunner_config() {
    log "Applying STUNner configuration..."
    
    local stunner_config_dir="${ROOT_DIR}/k8s/stunner"
    
    # Create namespaces
    kubectl apply -f "${stunner_config_dir}/00-namespaces.yaml"
    kubectl wait --for=condition=Active --timeout=60s namespace/stunner || true
    
    # Create auth secret
    log "Creating STUNner authentication secret..."
    kubectl create secret generic stunner-auth-secret \
        --from-literal=type=static \
        --from-literal=username="${TURN_USERNAME:-june-user}" \
        --from-literal=password="${STUNNER_PASSWORD:-Pokemon123!}" \
        --namespace=stunner-system \
        --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply configurations
    export PUBIP=$(curl -s ifconfig.me || echo "127.0.0.1")
    log "Using public IP: $PUBIP"
    
    for config_file in 20-dataplane-hostnet.yaml 30-gatewayconfig.yaml 40-gatewayclass.yaml 50-gateway.yaml; do
        log "Applying ${config_file}..."
        envsubst < "${stunner_config_dir}/${config_file}" | kubectl apply -f -
        sleep 5
    done
    
    # Create firewall rule
    log "Attempting to create GCP firewall rule for TURN server..."
    if command -v gcloud &> /dev/null; then
        gcloud compute firewall-rules create allow-turn-server \
            --allow udp:3478 \
            --source-ranges 0.0.0.0/0 \
            --description "Allow TURN server" \
            --quiet 2>/dev/null || warn "Firewall rule may already exist"
    fi
    
    success "STUNner configuration applied"
}

main() {
    log "Starting STUNner installation..."
    
    [ "$EUID" -ne 0 ] && error "Must run as root"
    
    verify_command "kubectl"
    verify_command "helm"
    
    systemctl stop coturn 2>/dev/null || true
    systemctl disable coturn 2>/dev/null || true
    
    install_gateway_api
    install_stunner
    apply_stunner_config
    
    EXTERNAL_IP=$(curl -s ifconfig.me || echo "127.0.0.1")
    success "STUNner installation completed"
    echo ""
    echo "🌐 TURN Server: turn:${EXTERNAL_IP}:3478"
    echo "   Username: ${TURN_USERNAME:-june-user}"
    echo "   Password: ${STUNNER_PASSWORD:-Pokemon123!}"
}

main "$@"
