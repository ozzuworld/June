#!/bin/bash
# June Platform - Phase 8: LiveKit Installation
# Installs LiveKit WebRTC server

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

# Get absolute path to avoid relative path issues
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Validate ROOT_DIR exists and has expected structure
if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Please run from June project directory or pass ROOT_DIR as argument"
fi

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

check_existing_livekit() {
    log "Checking for existing LiveKit installation..."
    
    if ! kubectl get namespace june-services &>/dev/null; then
        log "No existing LiveKit installation found (no june-services namespace)"
        return 1
    fi
    
    if helm list -n june-services 2>/dev/null | grep -q "livekit.*deployed"; then
        log "Found existing LiveKit Helm release"
        
        if kubectl get deployment livekit-livekit-server -n june-services &>/dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get deployment livekit-livekit-server -n june-services -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired_replicas
            desired_replicas=$(kubectl get deployment livekit-livekit-server -n june-services -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
            
            if [ "$ready_replicas" = "$desired_replicas" ] && [ "$ready_replicas" -gt 0 ]; then
                success "LiveKit is already installed and running ($ready_replicas/$desired_replicas replicas ready)"
                return 0
            else
                warn "LiveKit deployment exists but not all replicas are ready ($ready_replicas/$desired_replicas)"
            fi
        fi
    fi
    
    log "No existing LiveKit installation found"
    return 1
}

install_livekit() {
    log "Phase 8/10: Installing LiveKit..."
    
    if check_existing_livekit; then
        log "Skipping LiveKit installation - already deployed"
        return 0
    fi
    
    log "Creating june-services namespace..."
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

    local timeout=60
    local count=0
    while [ $count -lt $timeout ]; do
        if kubectl get namespace june-services --no-headers 2>/dev/null | grep -q "Active"; then
            log "june-services namespace is active"
            break
        fi
        sleep 1
        count=$((count + 1))
        if [ $count -eq $timeout ]; then
            error "Timeout waiting for june-services namespace to become active"
        fi
    done
    
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

generate_livekit_credentials() {
    log "Generating LiveKit API credentials..."
    
    export LIVEKIT_API_KEY="june-api-$(openssl rand -hex 16)"
    export LIVEKIT_API_SECRET="$(openssl rand -base64 32)"
    
    local creds_dir="${ROOT_DIR}/config/credentials"
    mkdir -p "$creds_dir"
    
    local creds_file="${creds_dir}/livekit-credentials.yaml"
    cat > "$creds_file" << EOF
livekit:
  api_key: "$LIVEKIT_API_KEY"
  api_secret: "$LIVEKIT_API_SECRET"
  server_url: "http://livekit.june-services.svc.cluster.local"
EOF

    local env_file="${creds_dir}/livekit.env"
    cat > "$env_file" << EOF
export LIVEKIT_API_KEY="$LIVEKIT_API_KEY"
export LIVEKIT_API_SECRET="$LIVEKIT_API_SECRET"
export LIVEKIT_URL="http://livekit.june-services.svc.cluster.local"
EOF

    success "LiveKit credentials generated and saved to:"
    log "  - YAML format: $creds_file"
    log "  - ENV format:  $env_file"
    
    log "LiveKit API Credentials:"
    log "  API Key:    $LIVEKIT_API_KEY"
    log "  API Secret: $LIVEKIT_API_SECRET"
    log "  Server URL: http://livekit.june-services.svc.cluster.local"
}

deploy_livekit_server() {
    log "Deploying LiveKit server..."
    
    if check_existing_livekit; then
        log "LiveKit server already deployed and ready"
        return 0
    fi
    
    local values_file="${ROOT_DIR}/k8s/livekit/livekit-values.yaml"
    
    if [ -f "$values_file" ]; then
        log "Using custom values file: $values_file"
        
        if [ -z "$LIVEKIT_API_KEY" ] || [ -z "$LIVEKIT_API_SECRET" ]; then
            generate_livekit_credentials
        fi
        
        envsubst < "$values_file" | helm upgrade --install livekit livekit/livekit-server \
            --namespace june-services \
            --values - \
            --wait \
            --timeout=15m > /dev/null 2>&1

    else
        warn "Values file not found at $values_file, using default configuration"
        
        generate_livekit_credentials
        
        helm upgrade --install livekit livekit/livekit-server \
            --namespace june-services \
            --set "livekit.keys.$LIVEKIT_API_KEY=$LIVEKIT_API_SECRET" \
            --set server.replicas=1 \
            --set server.resources.requests.cpu=100m \
            --set server.resources.requests.memory=128Mi \
            --wait \
            --timeout=15m > /dev/null 2>&1
    fi
    
    # 🔥 FIX: Helm chart bug - manually patch ConfigMap with correct ICE servers
    log "Patching ConfigMap to override Google/Twilio STUN servers..."
    kubectl patch configmap livekit-livekit-server -n june-services --type merge -p '
{
  "data": {
    "config.yaml": "keys:\n  devkey: bbUEBtMjPHrvdZwFEwcpPDJkePL5yTrJ\nlog_level: info\nport: 7880\nredis: {}\nrtc:\n  external_ip: \"34.59.178.219\"\n  port_range_end: 60000\n  port_range_start: 50000\n  tcp_port: 7881\n  udp_port: 7882\n  use_external_ip: true\n  stun_servers: []\n  turn_servers:\n    - host: turn.ozzu.world\n      port: 3478\n      protocol: udp\n      username: june-user\n      credential: Pokemon123!\nturn:\n  enabled: false\n  loadBalancerAnnotations: {}\n"
  }
}' > /dev/null 2>&1
    
    kubectl rollout restart deployment/livekit-livekit-server -n june-services > /dev/null 2>&1
    
    success "LiveKit server deployed with correct ICE servers"
}

wait_for_livekit() {
    log "Waiting for LiveKit to be ready..."
    
    wait_for_deployment "livekit-livekit-server" "june-services" 300
    
    success "LiveKit is ready"
}

apply_livekit_services() {
    log "Applying LiveKit additional services..."
    
    local livekit_config_dir="${ROOT_DIR}/k8s/livekit"
    
    if [ ! -d "$livekit_config_dir" ]; then
        warn "LiveKit configuration directory not found at $livekit_config_dir"
        return 0
    fi
    
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
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-june-services
  namespace: june-services
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
    
    verify_namespace "june-services"
    verify_k8s_resource "deployment" "livekit-livekit-server" "june-services"
    
    if kubectl get service livekit-livekit-server -n june-services &>/dev/null; then
        success "LiveKit service found"
        
        log "LiveKit service status:"
        kubectl get service livekit-livekit-server -n june-services
    else
        warn "LiveKit main service not found"
    fi
    
    if kubectl get service livekit-udp -n june-services &>/dev/null; then
        log "LiveKit UDP service found"
    else
        warn "LiveKit UDP service not found"
    fi
    
    log "LiveKit pod status:"
    kubectl get pods -n june-services | grep livekit
    
    local creds_file="${ROOT_DIR}/config/credentials/livekit-credentials.yaml"
    if [ -f "$creds_file" ]; then
        success "LiveKit credentials available at: $creds_file"
    fi
    
    success "LiveKit verification completed"
}

main() {
    log "Starting LiveKit installation phase..."
    
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    verify_command "kubectl" "kubectl must be available"
    verify_command "helm" "helm must be available"

    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster. Please ensure kubectl is configured correctly."
    fi

    if ! kubectl auth can-i create namespaces 2>/dev/null; then
        error "Insufficient permissions to create namespaces. Please ensure you have cluster-admin rights."
    fi

    if ! helm list -A &> /dev/null; then
        error "Helm cannot communicate with cluster. Please ensure Helm is properly configured."
    fi
    
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