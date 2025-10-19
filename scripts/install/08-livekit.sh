#!/bin/bash
# June Platform - Phase 8: LiveKit Installation
# Installs LiveKit WebRTC server in june-services namespace

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

# FIXED: Use june-services namespace consistently
LIVEKIT_NAMESPACE="june-services"

check_existing_livekit() {
    log "Checking for existing LiveKit installation..."
    
    if ! kubectl get namespace "$LIVEKIT_NAMESPACE" &>/dev/null; then
        log "No existing LiveKit installation found (no $LIVEKIT_NAMESPACE namespace)"
        return 1
    fi
    
    if helm list -n "$LIVEKIT_NAMESPACE" 2>/dev/null | grep -q "livekit.*deployed"; then
        log "Found existing LiveKit Helm release"
        
        if kubectl get deployment livekit-livekit-server -n "$LIVEKIT_NAMESPACE" &>/dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get deployment livekit-livekit-server -n "$LIVEKIT_NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired_replicas
            desired_replicas=$(kubectl get deployment livekit-livekit-server -n "$LIVEKIT_NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
            
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
    
    log "Creating $LIVEKIT_NAMESPACE namespace..."
    kubectl create namespace "$LIVEKIT_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

    local timeout=60
    local count=0
    while [ $count -lt $timeout ]; do
        if kubectl get namespace "$LIVEKIT_NAMESPACE" --no-headers 2>/dev/null | grep -q "Active"; then
            log "$LIVEKIT_NAMESPACE namespace is active"
            break
        fi
        sleep 1
        count=$((count + 1))
        if [ $count -eq $timeout ]; then
            error "Timeout waiting for $LIVEKIT_NAMESPACE namespace to become active"
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
    
    export LIVEKIT_API_KEY="devkey"
    export LIVEKIT_API_SECRET="bbUEBtMjPHrvdZwFEwcpPDJkePL5yTrJ"
    
    local creds_dir="${ROOT_DIR}/config/credentials"
    mkdir -p "$creds_dir"
    
    local creds_file="${creds_dir}/livekit-credentials.yaml"
    cat > "$creds_file" << EOF
livekit:
  api_key: "$LIVEKIT_API_KEY"
  api_secret: "$LIVEKIT_API_SECRET"
  server_url: "http://livekit-livekit-server.$LIVEKIT_NAMESPACE.svc.cluster.local"
EOF

    local env_file="${creds_dir}/livekit.env"
    cat > "$env_file" << EOF
export LIVEKIT_API_KEY="$LIVEKIT_API_KEY"
export LIVEKIT_API_SECRET="$LIVEKIT_API_SECRET"
export LIVEKIT_URL="http://livekit-livekit-server.$LIVEKIT_NAMESPACE.svc.cluster.local"
EOF

    success "LiveKit credentials generated and saved to:"
    log "  - YAML format: $creds_file"
    log "  - ENV format:  $env_file"
    
    log "LiveKit API Credentials:"
    log "  API Key:    $LIVEKIT_API_KEY"
    log "  API Secret: $LIVEKIT_API_SECRET"
    log "  Server URL: http://livekit-livekit-server.$LIVEKIT_NAMESPACE.svc.cluster.local"
}

deploy_livekit_server() {
    log "Deploying LiveKit server..."
    
    if check_existing_livekit; then
        log "LiveKit server already deployed and ready"
        return 0
    fi
    
    if [ -z "$LIVEKIT_API_KEY" ] || [ -z "$LIVEKIT_API_SECRET" ]; then
        generate_livekit_credentials
    fi
    
    # Get external IP for RTC configuration
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    export EXTERNAL_IP
    
    log "Using external IP: $EXTERNAL_IP for LiveKit RTC"
    
    helm upgrade --install livekit livekit/livekit-server \
        --namespace "$LIVEKIT_NAMESPACE" \
        --set "livekit.keys.$LIVEKIT_API_KEY=$LIVEKIT_API_SECRET" \
        --set server.replicas=1 \
        --set "server.config.rtc.external_ip=$EXTERNAL_IP" \
        --set server.config.rtc.udp_port=7882 \
        --set server.config.rtc.tcp_port=7881 \
        --set server.config.rtc.port_range_start=50000 \
        --set server.config.rtc.port_range_end=60000 \
        --set server.config.rtc.use_external_ip=true \
        --set server.config.rtc.stun_servers='[]' \
        --set "server.config.rtc.turn_servers[0].host=turn.$DOMAIN" \
        --set "server.config.rtc.turn_servers[0].port=3478" \
        --set "server.config.rtc.turn_servers[0].protocol=udp" \
        --set "server.config.rtc.turn_servers[0].username=$TURN_USERNAME" \
        --set "server.config.rtc.turn_servers[0].credential=$STUNNER_PASSWORD" \
        --wait \
        --timeout=15m > /dev/null 2>&1
    
    success "LiveKit server deployed"
}

wait_for_livekit() {
    log "Waiting for LiveKit to be ready..."
    
    wait_for_deployment "livekit-livekit-server" "$LIVEKIT_NAMESPACE" 300
    
    success "LiveKit is ready"
}

create_livekit_udp_service() {
    log "Creating LiveKit UDP service..."
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: v1
kind: Service
metadata:
  name: livekit-udp
  namespace: $LIVEKIT_NAMESPACE
  labels:
    app: livekit
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: livekit-server
  ports:
  - name: udp
    port: 7882
    targetPort: 7882
    protocol: UDP
EOF
    
    success "LiveKit UDP service created"
}

setup_udproute() {
    log "Setting up UDPRoute for LiveKit..."
    
    if ! kubectl get gateway stunner-gateway -n stunner &>/dev/null; then
        warn "STUNner gateway not found, skipping UDPRoute creation"
        return 0
    fi
    
    # Create UDPRoute pointing to LiveKit in june-services namespace
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: stunner.l7mp.io/v1
kind: UDPRoute
metadata:
  name: livekit-udp-route
  namespace: stunner
spec:
  parentRefs:
    - name: stunner-gateway
  rules:
    - backendRefs:
        - name: livekit-udp
          namespace: $LIVEKIT_NAMESPACE
          port: 7882
EOF
    
    success "UDPRoute applied successfully"
}

setup_reference_grant() {
    log "Setting up ReferenceGrant for cross-namespace access..."
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-june-services
  namespace: $LIVEKIT_NAMESPACE
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
    
    verify_namespace "$LIVEKIT_NAMESPACE"
    verify_k8s_resource "deployment" "livekit-livekit-server" "$LIVEKIT_NAMESPACE"
    
    if kubectl get service livekit-livekit-server -n "$LIVEKIT_NAMESPACE" &>/dev/null; then
        success "LiveKit service found"
        
        log "LiveKit service status:"
        kubectl get service livekit-livekit-server -n "$LIVEKIT_NAMESPACE"
    else
        warn "LiveKit main service not found"
    fi
    
    if kubectl get service livekit-udp -n "$LIVEKIT_NAMESPACE" &>/dev/null; then
        log "LiveKit UDP service found"
    else
        warn "LiveKit UDP service not found"
    fi
    
    log "LiveKit pod status:"
    kubectl get pods -n "$LIVEKIT_NAMESPACE" | grep livekit || echo "No LiveKit pods found"
    
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
        error "Cannot connect to Kubernetes cluster"
    fi
    
    install_livekit
    deploy_livekit_server
    wait_for_livekit
    create_livekit_udp_service
    setup_udproute
    setup_reference_grant
    verify_livekit
    
    success "LiveKit installation phase completed"
}

main "$@"