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
STORAGE_CLASS=""  # Auto-detected

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
    
    # Last resort: list available classes and let user choose
    log_warning "No suitable dynamic storage class found automatically."
    log_info "Available storage classes:"
    kubectl get storageclass -o custom-columns="NAME:.metadata.name,PROVISIONER:.provisioner,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class"
    
    log_error "Please set a default storage class or specify one with: helm install --set global.storageClass=YOUR_CLASS"
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

# Validate and fix MinIO credentials
validate_minio_credentials() {
    log_info "Validating MinIO credentials..."
    
    # Wait for MinIO secret to exist
    local retries=0
    while ! kubectl get secret opencti-minio -n "$NAMESPACE" &> /dev/null && [ $retries -lt 30 ]; do
        log_info "Waiting for MinIO secret to be created..."
        sleep 5
        ((retries++))
    done
    
    if ! kubectl get secret opencti-minio -n "$NAMESPACE" &> /dev/null; then
        log_warning "MinIO secret not found, will be created during deployment"
        return
    fi
    
    # Check current credentials
    local current_user current_pass
    current_user=$(kubectl get secret opencti-minio -n "$NAMESPACE" -o jsonpath='{.data.rootUser}' | base64 -d 2>/dev/null || echo "")
    current_pass=$(kubectl get secret opencti-minio -n "$NAMESPACE" -o jsonpath='{.data.rootPassword}' | base64 -d 2>/dev/null || echo "")
    
    # Expected credentials from values-fixed.yaml
    local expected_user="opencti"
    local expected_pass="MinIO2024!"
    
    if [[ "$current_user" != "$expected_user" || "$current_pass" != "$expected_pass" ]]; then
        log_warning "MinIO credentials don't match values-fixed.yaml, fixing..."
        
        kubectl patch secret opencti-minio -n "$NAMESPACE" --type='json' -p="[
            {\"op\":\"replace\",\"path\":\"/data/rootUser\",\"value\":\"$(echo -n "$expected_user" | base64 -w 0)\"},
            {\"op\":\"replace\",\"path\":\"/data/rootPassword\",\"value\":\"$(echo -n "$expected_pass" | base64 -w 0)\"}
        ]"
        
        # Restart MinIO pod to pick up new credentials
        kubectl delete pod -l app=minio -n "$NAMESPACE" --ignore-not-found=true
        kubectl wait --for=condition=ready pod -l app=minio -n "$NAMESPACE" --timeout=120s
        
        log_success "MinIO credentials aligned with values-fixed.yaml"
    else
        log_success "MinIO credentials are correctly configured"
    fi
}

# Deploy OpenCTI
deploy_opencti() {
    log_info "Deploying OpenCTI using values-fixed.yaml with storage class: $STORAGE_CLASS"
    
    # Prepare Helm command with storage class override
    local helm_args=()
    if [[ -n "$STORAGE_CLASS" ]]; then
        helm_args+=("--set" "global.storageClass=$STORAGE_CLASS")
    fi
    
    # Deploy using Helm
    if helm list -n "$NAMESPACE" | grep -q "$RELEASE_NAME"; then
        log_info "Upgrading existing OpenCTI deployment..."
        helm upgrade "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$VALUES_FILE" \
            "${helm_args[@]}" \
            --timeout 25m0s \
            --wait
    else
        log_info "Installing OpenCTI..."
        helm upgrade --install "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$VALUES_FILE" \
            "${helm_args[@]}" \
            --timeout 25m0s \
            --wait
    fi
    
    log_success "OpenCTI deployment completed"
}

# Reset OpenSearch for clean initialization
reset_opensearch() {
    log_info "Resetting OpenSearch for clean initialization..."
    
    if [ -f "k8s/opencti/opensearch-reset.sh" ]; then
        bash k8s/opencti/opensearch-reset.sh "$NAMESPACE"
    else
        log_warning "opensearch-reset.sh not found, skipping OpenSearch reset"
    fi
}

# Bootstrap admin credentials
bootstrap_admin() {
    log_info "Bootstrapping OpenCTI admin credentials..."
    
    if [ -f "k8s/opencti/bootstrap-admin.sh" ]; then
        bash k8s/opencti/bootstrap-admin.sh "$NAMESPACE"
    else
        log_warning "bootstrap-admin.sh not found, admin credentials not configured"
        log_warning "You may need to manually set valid UUIDv4 admin token"
    fi
}

# Wait for services
wait_for_services() {
    log_info "Waiting for OpenCTI services to be ready..."
    
    # Wait for dependencies first
    log_info "Waiting for Redis..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=redis -n "$NAMESPACE" --timeout=300s || true
    
    log_info "Waiting for OpenSearch..."
    kubectl wait --for=condition=ready pod -l app=opensearch-cluster-master -n "$NAMESPACE" --timeout=600s || true
    
    log_info "Waiting for RabbitMQ..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=rabbitmq -n "$NAMESPACE" --timeout=300s || true
    
    log_info "Waiting for MinIO..."
    kubectl wait --for=condition=ready pod -l app=minio -n "$NAMESPACE" --timeout=300s || true
    
    log_success "Dependencies are ready"
}

# Show deployment status
show_status() {
    log_info "OpenCTI Deployment Status:"
    echo
    
    # Show storage class used
    if [[ -n "$STORAGE_CLASS" ]]; then
        log_info "Storage Class: $STORAGE_CLASS"
    fi
    
    # Show pods
    log_info "Pods:"
    kubectl get pods -n "$NAMESPACE" -o wide
    echo
    
    # Show services
    log_info "Services:"
    kubectl get svc -n "$NAMESPACE"
    echo
    
    # Show PVCs and their status
    log_info "Storage (PVCs):"
    kubectl get pvc -n "$NAMESPACE" -o wide
    echo
    
    # Show ingress
    log_info "Ingress:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || log_warning "No ingress found"
    echo
    
    log_success "OpenCTI should be accessible at: https://opencti.ozzu.world"
    echo
    log_info "Default credentials are set in values-fixed.yaml"
    log_warning "Remember to change default passwords in production!"
}

# Get logs function
get_logs() {
    log_info "Recent OpenCTI server logs:"
    kubectl logs -l opencti.component=server -n "$NAMESPACE" --tail=50 2>/dev/null || \
        log_warning "No OpenCTI server pods found or logs not available"
}

# Cleanup function
cleanup_deployment() {
    log_warning "This will remove the entire OpenCTI deployment. Are you sure? (y/N)"
    read -r confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        log_info "Removing OpenCTI deployment..."
        helm uninstall "$RELEASE_NAME" -n "$NAMESPACE" 2>/dev/null || true
        kubectl delete namespace "$NAMESPACE" --ignore-not-found=true
        log_success "OpenCTI deployment removed"
    else
        log_info "Cleanup cancelled"
    fi
}

# Main execution
main() {
    log_info "Starting OpenCTI deployment with storage class detection..."
    
    check_prerequisites
    detect_storage_class
    add_helm_repo
    create_namespace
    deploy_opencti
    
    # Validate and fix MinIO credentials after deployment
    validate_minio_credentials
    
    # Wait for services if requested
    if [ "${WAIT_FOR_READY:-true}" = "true" ]; then
        wait_for_services
    fi
    
    # Bootstrap admin if requested
    if [ "${BOOTSTRAP_ADMIN:-true}" = "true" ]; then
        bootstrap_admin
    fi
    
    show_status
    
    log_success "OpenCTI deployment completed successfully!"
    log_info "If initialization fails, run: $0 --reset"
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
        --no-wait)
            WAIT_FOR_READY="false"
            shift
            ;;
        --no-bootstrap)
            BOOTSTRAP_ADMIN="false"
            shift
            ;;
        --reset)
            reset_opensearch
            exit 0
            ;;
        --logs)
            get_logs
            exit 0
            ;;
        --status)
            show_status
            exit 0
            ;;
        --cleanup)
            cleanup_deployment
            exit 0
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --namespace NAMESPACE      Kubernetes namespace (default: opencti)"
            echo "  --release-name NAME        Helm release name (default: opencti)"
            echo "  --storage-class CLASS      Override storage class (auto-detected by default)"
            echo "  --no-wait                 Don't wait for deployment to be ready"
            echo "  --no-bootstrap            Skip admin credential bootstrap"
            echo "  --reset                   Reset OpenSearch for clean initialization"
            echo "  --logs                    Show recent application logs"
            echo "  --status                  Show deployment status"
            echo "  --cleanup                 Remove OpenCTI deployment"
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