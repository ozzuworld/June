#!/bin/bash
# June Platform - Phase 8: June Platform Deployment
# Deploys June Platform core services using Helm

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

# Get absolute path to avoid relative path issues
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Validate ROOT_DIR exists and has expected structure
if [ ! -d "$ROOT_DIR" ] || [ ! -d "$ROOT_DIR/scripts" ]; then
    error "Cannot determine ROOT_DIR. Current: $ROOT_DIR"
    error "Please run from June project directory or pass ROOT_DIR as argument"
    error "Expected structure: ROOT_DIR/scripts/install/"
    exit 1
fi

log "Using ROOT_DIR: $ROOT_DIR"

# Debug path information
log "SCRIPT_DIR: $SCRIPT_DIR"
log "ROOT_DIR: $ROOT_DIR"
log "Current working directory: $(pwd)"

# Validate key directories exist
if [ ! -d "$ROOT_DIR/k8s" ]; then
    warn "k8s directory not found at $ROOT_DIR/k8s"
fi

if [ ! -d "$ROOT_DIR/config" ]; then
    warn "config directory not found at $ROOT_DIR/config"
fi

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

detect_gpu() {
    log "Detecting GPU availability..."
    
    local gpu_available="false"
    
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        gpu_available="true"
        log "GPU detected - STT and TTS will be enabled"
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits | head -1
    else
        log "No GPU detected - STT and TTS will be disabled"
    fi
    
    echo "$gpu_available"
}

setup_june_namespace() {
    log "Setting up June services namespace..."
    
    # Create june-services namespace
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Wait for namespace with better error handling
    local timeout=60
    local count=0
    while [ $count -lt $timeout ]; do
        if kubectl get namespace june-services --no-headers 2>/dev/null | grep -q "Active"; then
            log "June services namespace is active"
            break
        fi
        sleep 1
        count=$((count + 1))
        if [ $count -eq $timeout ]; then
            error "Timeout waiting for June services namespace to become active"
        fi
    done
    
    success "June services namespace ready"
}

validate_helm_chart() {
    local helm_chart="$1"
    
    log "Validating Helm chart at: $helm_chart"
    
    if [ ! -d "$helm_chart" ]; then
        error "Helm chart not found at: $helm_chart"
    fi
    
    # Ensure Chart.yaml exists (case-insensitive check)
    if [ ! -f "$helm_chart/Chart.yaml" ] && [ -f "$helm_chart/chart.yaml" ]; then
        mv "$helm_chart/chart.yaml" "$helm_chart/Chart.yaml"
        log "Renamed chart.yaml to Chart.yaml"
    fi
    
    if [ ! -f "$helm_chart/Chart.yaml" ]; then
        error "Chart.yaml not found in Helm chart directory"
    fi
    
    success "Helm chart validation passed"
}

validate_environment() {
    log "Validating environment variables..."
    
    local required_vars=(
        "DOMAIN"
        "LETSENCRYPT_EMAIL"
        "GEMINI_API_KEY"
        "CLOUDFLARE_TOKEN"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            error "Required environment variable $var is not set"
        fi
    done
    
    success "Environment variables validated"
}

deploy_june_platform() {
    log "Phase 8/9: Deploying June Platform..."
    
    local helm_chart="$ROOT_DIR/helm/june-platform"
    local gpu_available
    gpu_available=$(detect_gpu)
    
    validate_helm_chart "$helm_chart"
    validate_environment
    
    log "Deploying June Platform services..."
    log "Configuration:"
    log "  Domain: $DOMAIN"
    log "  GPU Available: $gpu_available"
    log "  Email: $LETSENCRYPT_EMAIL"
    
    # Deploy June Platform using Helm
    helm upgrade --install june-platform "$helm_chart" \
        --namespace june-services \
        --set global.domain="$DOMAIN" \
        --set certificate.email="$LETSENCRYPT_EMAIL" \
        --set secrets.geminiApiKey="$GEMINI_API_KEY" \
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN" \
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}" \
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}" \
        --set stt.enabled="$gpu_available" \
        --set tts.enabled="$gpu_available" \
        --set certificate.enabled=true \
        --timeout 15m
    
    success "June Platform deployed"
}

wait_for_core_services() {
    log "Waiting for core services to be ready..."
    
    local services=(
        "june-orchestrator"
        "june-idp"
        "june-postgresql"
    )
    
    for service in "${services[@]}"; do
        log "Waiting for $service..."
        if kubectl get deployment "$service" -n june-services &>/dev/null; then
            wait_for_deployment "$service" "june-services" 300
        else
            warn "Deployment $service not found, skipping wait"
        fi
    done
    
    success "Core services are ready"
}

wait_for_ai_services() {
    local gpu_available
    gpu_available=$(detect_gpu)
    
    if [ "$gpu_available" = "true" ]; then
        log "Waiting for AI services (GPU enabled)..."
        
        local ai_services=(
            "june-stt"
            "june-tts"
        )
        
        for service in "${ai_services[@]}"; do
            log "Waiting for $service..."
            if kubectl get deployment "$service" -n june-services &>/dev/null; then
                wait_for_deployment "$service" "june-services" 600  # AI services need more time
            else
                warn "AI service $service not found, skipping wait"
            fi
        done
        
        success "AI services are ready"
    else
        log "Skipping AI services (no GPU available)"
    fi
}

verify_june_platform() {
    log "Verifying June Platform deployment..."
    
    # Check namespace
    verify_namespace "june-services"
    
    # Check core deployments
    local core_services=(
        "june-orchestrator"
        "june-idp"
        "june-postgresql"
    )
    
    for service in "${core_services[@]}"; do
        if kubectl get deployment "$service" -n june-services &>/dev/null; then
            log "✓ $service deployment found"
        else
            warn "✗ $service deployment not found"
        fi
    done
    
    # Check AI services if GPU is available
    local gpu_available
    gpu_available=$(detect_gpu)
    
    if [ "$gpu_available" = "true" ]; then
        local ai_services=("june-stt" "june-tts")
        for service in "${ai_services[@]}"; do
            if kubectl get deployment "$service" -n june-services &>/dev/null; then
                log "✓ $service deployment found"
            else
                warn "✗ $service deployment not found"
            fi
        done
    fi
    
    # Show deployment status
    log "June Platform status:"
    kubectl get pods -n june-services
    kubectl get services -n june-services
    kubectl get ingress -n june-services
    
    success "June Platform verification completed"
}

# Main execution
main() {
    log "Starting June Platform deployment phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify Kubernetes connectivity with better error messages
    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster. Please ensure kubectl is configured correctly."
    fi
    
    # Check if user has sufficient permissions
    if ! kubectl auth can-i create namespaces 2>/dev/null; then
        error "Insufficient permissions to create namespaces. Please ensure you have cluster-admin rights."
    fi
    
    # Verify Helm can communicate with cluster
    if ! helm list -A &> /dev/null; then
        error "Helm cannot communicate with cluster. Please ensure Helm is properly configured."
    fi
    
    # Verify prerequisites
    verify_command "kubectl" "kubectl must be available"
    verify_command "helm" "helm must be available"
    
    setup_june_namespace
    deploy_june_platform
    wait_for_core_services
    wait_for_ai_services
    verify_june_platform
    
    success "June Platform deployment phase completed"
}

main "$@"