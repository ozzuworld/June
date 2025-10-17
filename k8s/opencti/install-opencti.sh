#!/bin/bash

# OpenCTI Deployment Script with Storage Class Detection
# This script deploys OpenCTI with proper credential alignment and storage configuration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="opencti"
RELEASE_NAME="opencti"
CHART_REPO="https://devops-ia.github.io/helm-opencti"
CHART_NAME="opencti/opencti"
VALUES_FILE="k8s/opencti/values-fixed.yaml"
STORAGE_CLASS=""  # Auto-detected or overridden

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Detect best available storage class
detect_storage_class() {
    # If user specified --storage-class, respect it
    if [[ -n "$STORAGE_CLASS" ]]; then
        log_info "Using provided storage class: $STORAGE_CLASS"
        return
    }

    log_info "Detecting available storage classes..."
    
    # Check if any storage classes exist
    if ! kubectl get storageclass &> /dev/null; then
        log_error "No storage classes found. Please configure a storage provisioner."
    fi
    
    # Try to find default storage class
    local default_sc
    default_sc=$(kubectl get storageclass -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}' 2>/dev/null || echo "")
    
    if [[ -n "$default_sc" ]]; then
        STORAGE_CLASS="$default_sc"
        log_success "Using default storage class: $STORAGE_CLASS"
        return
    fi
    
    # No default found, look for common dynamic provisioners
    local common_classes=("gp2" "gp3" "standard" "ssd" "fast" "do-block-storage" "rook-ceph-block" "longhorn")
    
    for class in "${common_classes[@]}"; do
        if kubectl get storageclass "$class" &> /dev/null; then
            # Check if it's a dynamic provisioner (not local storage)
            local provisioner
            provisioner=$(kubectl get storageclass "$class" -o jsonpath='{.provisioner}' 2>/dev/null || echo "")
            
            if [[ "$provisioner" != "kubernetes.io/no-provisioner" && "$provisioner" != *"local"* ]]; then
                STORAGE_CLASS="$class"
                log_success "Using storage class: $STORAGE_CLASS (provisioner: $provisioner)"
                return
            fi
        fi
    done
    
    # Fallback: use first available dynamic provisioner
    local first_dynamic
    first_dynamic=$(kubectl get storageclass -o jsonpath='{.items[?(@.provisioner!="kubernetes.io/no-provisioner")].metadata.name}' | awk '{print $1}' 2>/dev/null || echo "")
    
    if [[ -n "$first_dynamic" ]]; then
        STORAGE_CLASS="$first_dynamic"
        local provisioner
        provisioner=$(kubectl get storageclass "$first_dynamic" -o jsonpath='{.provisioner}' 2>/dev/null || echo "unknown")
        log_warning "Using first available dynamic storage class: $STORAGE_CLASS (provisioner: $provisioner)"
        return
    fi
    
    # Last resort: if only local-storage exists, leave STORAGE_CLASS empty
    # and rely on manual PVs + PVCs (as configured in the repo docs)
    log_warning "No suitable dynamic storage class found automatically; proceeding with manual/local PVs."
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
    fi
    
    # Check if helm is available
    if ! command -v helm &> /dev/null; then
        log_error "helm is not installed or not in PATH"
    fi
    
    # Check if cluster is accessible
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
    fi
    
    # Check if values file exists
    if [ ! -f "$VALUES_FILE" ]; then
        log_error "Values file not found: $VALUES_FILE"
    fi
    
    log_success "Prerequisites check passed"
}

# Add Helm repository
add_helm_repo() {
    log_info "Adding OpenCTI Helm repository..."
    
    # Add repository
    helm repo add opencti "$CHART_REPO" 2>/dev/null || true
    helm repo update
    
    # Verify chart is available
    if ! helm search repo opencti/opencti &> /dev/null; then
        log_error "OpenCTI chart not found in repository"
    fi
    
    log_success "Helm repository configured"
}

# Create namespace
create_namespace() {
    log_info "Creating namespace: $NAMESPACE"
    
    # Create namespace with labels
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | \
        kubectl label --local -f - name="$NAMESPACE" -o yaml | \
        kubectl apply -f -
    
    log_success "Namespace '$NAMESPACE' ready"
}

# Deploy OpenCTI
deploy_opencti() {
    log_info "Deploying OpenCTI using values-fixed.yaml..."
    
    # Prepare Helm args
    local helm_args=(
        "--namespace" "$NAMESPACE"
        "--values" "$VALUES_FILE"
        # Enforce ELASTICSEARCH__URL env at deploy time
        "--set" "opencti.server.extraEnv[0].name=ELASTICSEARCH__URL"
        "--set" "opencti.server.extraEnv[0].value=http://opensearch-cluster-master:9200"
    )

    # Include storage class override if we have one
    if [[ -n "$STORAGE_CLASS" ]]; then
        helm_args+=("--set" "global.storageClass=$STORAGE_CLASS")
    fi
    
    # Install or upgrade
    if helm list -n "$NAMESPACE" | grep -q "$RELEASE_NAME"; then
        log_info "Upgrading existing OpenCTI deployment..."
        helm upgrade "$RELEASE_NAME" "$CHART_NAME" \
            "${helm_args[@]}" \
            --timeout 25m0s \
            --wait
    else
        log_info "Installing OpenCTI..."
        helm upgrade --install "$RELEASE_NAME" "$CHART_NAME" \
            "${helm_args[@]}" \
            --timeout 25m0s \
            --wait
    fi
    
    log_success "OpenCTI deployment completed"
}

# Validate server environment variables
validate_server_env() {
    log_info "Validating OpenCTI server environment..."
    local env_url
    env_url=$(kubectl get deployment opencti-server -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="ELASTICSEARCH__URL")].value}' || true)
    if [[ "$env_url" != "http://opensearch-cluster-master:9200" ]]; then
        log_error "ELASTICSEARCH__URL is '$env_url' (expected http://opensearch-cluster-master:9200). Aborting to avoid bad rollout."
    fi
    log_success "OpenCTI server env validated (ELASTICSEARCH__URL correct)"
}

# Main execution
main() {
    log_info "Starting OpenCTI deployment with deterministic configuration..."
    
    check_prerequisites
    detect_storage_class
    add_helm_repo
    create_namespace
    deploy_opencti
    validate_server_env
    
    log_success "OpenCTI deployment completed successfully!"
    log_info "Next: run bootstrap-admin.sh if not already done."
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --release-name)
            RELEASE_NAME="$2"
            shift 2
            ;;
        --storage-class)
            STORAGE_CLASS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --namespace NAMESPACE      Kubernetes namespace (default: opencti)"
            echo "  --release-name NAME        Helm release name (default: opencti)"
            echo "  --storage-class CLASS      Override storage class (auto-detected by default)"
            echo "  --help                    Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1. Use --help for usage information."
            ;;
    esac
done

# Run main function
main
