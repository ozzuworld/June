#!/bin/bash
# June Platform - Phase 9: June Platform Deployment
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

# Default flags to disable local STT/TTS unless explicitly enabled
ENABLE_STT=${ENABLE_STT:-false}
ENABLE_TTS=${ENABLE_TTS:-false}

# Normalize values to true/false
normalize_bool() {
    case "${1,,}" in
        true|1|yes|y|on) echo true ;;
        false|0|no|n|off|"") echo false ;;
        *) echo false ;;
    esac
}

ENABLE_STT=$(normalize_bool "$ENABLE_STT")
ENABLE_TTS=$(normalize_bool "$ENABLE_TTS")

log "Local AI services configuration: ENABLE_STT=$ENABLE_STT, ENABLE_TTS=$ENABLE_TTS"

# GPU detection is used only for info, not to force-enable local AI services
detect_gpu() {
    log "Detecting GPU availability..."
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        log "GPU detected"
        echo true
    else
        log "No GPU detected"
        echo false
    fi
}

setup_june_namespace() {
    log "Setting up June services namespace..."
    if kubectl get namespace june-services >/dev/null 2>&1; then
        local managed_by=$(kubectl get namespace june-services -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null || echo "")
        if [ "$managed_by" != "Helm" ]; then
            log "Existing namespace found without Helm ownership - adding Helm labels..."
            kubectl label namespace june-services app.kubernetes.io/managed-by=Helm --overwrite
            kubectl annotate namespace june-services meta.helm.sh/release-name=june-platform --overwrite
            kubectl annotate namespace june-services meta.helm.sh/release-namespace=june-services --overwrite
            log "Namespace ownership transferred to Helm"
        else
            log "Namespace already managed by Helm"
        fi
        NAMESPACE_EXISTS=true
    else
        log "Namespace will be created by Helm during deployment"
        NAMESPACE_EXISTS=false
    fi
    success "June services namespace ready"
}

validate_helm_chart() {
    local helm_chart="$1"
    log "Validating Helm chart at: $helm_chart"
    if [ ! -d "$helm_chart" ]; then
        error "Helm chart not found at: $helm_chart"
    fi
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

build_ai_helm_values() {
    local values=""
    # Respect explicit ENABLE_STT/ENABLE_TTS; default false
    if [ "$ENABLE_STT" = true ]; then
        values="$values --set stt.enabled=true"
    else
        values="$values --set stt.enabled=false"
    fi
    if [ "$ENABLE_TTS" = true ]; then
        values="$values --set tts.enabled=true"
    else
        values="$values --set tts.enabled=false"
    fi
    echo "$values"
}

deploy_june_platform() {
    log "Phase 9/10: Deploying June Platform..."
    local helm_chart="$ROOT_DIR/helm/june-platform"
    validate_helm_chart "$helm_chart"
    validate_environment

    log "Deploying June Platform services..."
    log "  Domain: $DOMAIN"
    log "  Email: $LETSENCRYPT_EMAIL"
    log "  ENABLE_STT=$ENABLE_STT, ENABLE_TTS=$ENABLE_TTS (local deployments)"

    local helm_cmd="helm upgrade --install june-platform \"$helm_chart\" \
        --namespace june-services"

    if [ "$NAMESPACE_EXISTS" = "false" ]; then
        helm_cmd="$helm_cmd \
        --create-namespace"
        log "Using --create-namespace flag (namespace doesn't exist)"
    else
        log "Skipping --create-namespace flag (namespace already exists)"
    fi

    # Core values
    helm_cmd="$helm_cmd \
        --set global.domain=\"$DOMAIN\" \
        --set certificate.email=\"$LETSENCRYPT_EMAIL\" \
        --set secrets.geminiApiKey=\"$GEMINI_API_KEY\" \
        --set secrets.cloudflareToken=\"$CLOUDFLARE_TOKEN\" \
        --set postgresql.password=\"${POSTGRESQL_PASSWORD:-Pokemon123!}\" \
        --set keycloak.adminPassword=\"${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}\" \
        --set certificate.enabled=true \
        --timeout 15m"

    # AI service toggles (explicit)
    helm_cmd="$helm_cmd $(build_ai_helm_values)"

    eval "$helm_cmd"
    success "June Platform deployed"
}

wait_for_core_services() {
    log "Waiting for core services to be ready..."
    local services=("june-orchestrator" "june-idp" "june-postgresql")
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
    # Only wait if explicitly enabled locally
    if [ "$ENABLE_STT" = true ] || [ "$ENABLE_TTS" = true ]; then
        log "Waiting for local AI services..."
        for service in june-stt june-tts; do
            if kubectl get deployment "$service" -n june-services &>/dev/null; then
                wait_for_deployment "$service" "june-services" 600
            else
                warn "AI service $service not found or disabled, skipping wait"
            fi
        done
        success "AI services check completed"
    else
        log "Skipping local AI services (disabled via config)"
    fi
}

verify_june_platform() {
    log "Verifying June Platform deployment..."
    verify_namespace "june-services"
    local core_services=("june-orchestrator" "june-idp" "june-postgresql")
    for service in "${core_services[@]}"; do
        if kubectl get deployment "$service" -n june-services &>/dev/null; then
            log "✓ $service deployment found"
        else
            warn "✗ $service deployment not found"
        fi
    done
    if [ "$ENABLE_STT" = true ] || [ "$ENABLE_TTS" = true ]; then
        for service in june-stt june-tts; do
            if kubectl get deployment "$service" -n june-services &>/devNull; then
                log "✓ $service deployment found"
            else
                warn "✗ $service deployment not found (disabled or not installed)"
            fi
        done
    fi
    log "June Platform status:"
    kubectl get pods -n june-services
    kubectl get services -n june-services
    kubectl get ingress -n june-services
    success "June Platform verification completed"
}

main() {
    log "Starting June Platform deployment phase..."
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster. Please ensure kubectl is configured correctly."
    fi
    if ! kubectl auth can-i create namespaces 2>/dev/null; then
        error "Insufficient permissions to create namespaces. Please ensure you have cluster-admin rights."
    fi
    if ! helm list -A &> /dev/null; then
        error "Helm cannot communicate with cluster. Please ensure Helm is properly configured."
    fi
    verify_command "kubectl" "kubectl must be available"
    verify_command "helm" "helm must be available"
    NAMESPACE_EXISTS=false
    setup_june_namespace
    deploy_june_platform
    wait_for_core_services
    wait_for_ai_services
    verify_june_platform
    success "June Platform deployment phase completed"
}

main "$@"
