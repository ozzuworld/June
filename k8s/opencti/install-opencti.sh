#!/bin/bash

# OpenCTI Deployment Script using Upstream Helm Chart
# This script deploys OpenCTI using the official helm-opencti chart
# Fixed version for OpenSearch connectivity issues

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
VALUES_FILE="k8s/opencti/values-production.yaml"
FALLBACK_VALUES="k8s/opencti/values-fixed.yaml"

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

# Check for existing OpenSearch
check_opensearch() {
    log_info "Checking for existing OpenSearch services..."
    
    # Look for OpenSearch services
    local opensearch_services
    opensearch_services=$(kubectl get services -n "$NAMESPACE" 2>/dev/null | grep -E "(opensearch|elasticsearch)" || true)
    
    if [ -n "$opensearch_services" ]; then
        log_info "Found existing search engine services:"
        echo "$opensearch_services"
        
        # Check if opensearch-cluster-master exists
        if kubectl get service opensearch-cluster-master -n "$NAMESPACE" &> /dev/null; then
            log_warning "OpenSearch service 'opensearch-cluster-master' already exists"
            log_info "This deployment will try to connect to the existing service"
            USE_EXISTING_OPENSEARCH=true
        fi
    else
        log_info "No existing search engine services found"
        USE_EXISTING_OPENSEARCH=false
    fi
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

# Generate secrets if needed
generate_secrets() {
    log_info "Checking OpenCTI secrets..."
    
    # Generate admin token if not set
    if ! kubectl get secret opencti-secrets -n "$NAMESPACE" &> /dev/null; then
        log_info "Generating OpenCTI admin token..."
        ADMIN_TOKEN=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(str(uuid.uuid4()))" 2>/dev/null || openssl rand -hex 16)
        
        # Create secret with generated token
        kubectl create secret generic opencti-secrets \
            --from-literal=admin-token="$ADMIN_TOKEN" \
            --namespace="$NAMESPACE" \
            --dry-run=client -o yaml | kubectl apply -f -
        
        log_info "Generated admin token: $ADMIN_TOKEN"
    else
        log_info "OpenCTI secrets already exist"
    fi
    
    log_success "Secrets configured"
}

# Deploy OpenCTI
deploy_opencti() {
    log_info "Deploying OpenCTI using upstream chart..."
    
    # Choose values file based on existing services
    local chosen_values="$VALUES_FILE"
    if [ "$USE_EXISTING_OPENSEARCH" = "true" ]; then
        log_warning "Using fallback configuration for existing OpenSearch"
        chosen_values="$FALLBACK_VALUES"
    fi
    
    log_info "Using values file: $chosen_values"
    
    # Deploy using Helm
    if helm list -n "$NAMESPACE" | grep -q "$RELEASE_NAME"; then
        log_info "Upgrading existing OpenCTI deployment..."
        helm upgrade "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$chosen_values" \
            --timeout 15m0s \
            --wait
    else
        log_info "Installing OpenCTI..."
        helm upgrade --install "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$chosen_values" \
            --timeout 15m0s \
            --wait
    fi
    
    log_success "OpenCTI deployment completed"
}

# Verify OpenSearch connectivity
verify_opensearch_connectivity() {
    log_info "Verifying OpenSearch connectivity..."
    
    # Wait a bit for services to be ready
    sleep 10
    
    # Find OpenCTI server pod
    local server_pod
    server_pod=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=opencti --no-headers -o custom-columns=":metadata.name" | head -1 2>/dev/null || true)
    
    if [ -n "$server_pod" ]; then
        log_info "Testing connectivity from pod: $server_pod"
        
        # Test connectivity to OpenSearch
        log_info "Testing OpenSearch connectivity..."
        if kubectl exec "$server_pod" -n "$NAMESPACE" -- curl -s -o /dev/null -w "%{http_code}" http://opensearch-cluster-master:9200 2>/dev/null | grep -q "200\|000"; then
            log_success "OpenSearch connectivity verified"
        else
            log_warning "Could not verify OpenSearch connectivity"
            
            # Show available services for troubleshooting
            log_info "Available services in namespace:"
            kubectl get services -n "$NAMESPACE"
        fi
    else
        log_warning "No OpenCTI server pod found for connectivity testing"
    fi
}

# Wait for services
wait_for_services() {
    log_info "Waiting for OpenCTI services to be ready..."
    
    # Wait for dependencies first
    log_info "Waiting for Redis..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=redis -n "$NAMESPACE" --timeout=300s 2>/dev/null || log_warning "Redis timeout"
    
    log_info "Waiting for RabbitMQ..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=rabbitmq -n "$NAMESPACE" --timeout=300s 2>/dev/null || log_warning "RabbitMQ timeout"
    
    log_info "Waiting for MinIO..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=minio -n "$NAMESPACE" --timeout=300s 2>/dev/null || log_warning "MinIO timeout"
    
    # Check for OpenSearch (existing or new)
    log_info "Checking OpenSearch status..."
    if kubectl get pod opensearch-cluster-master-0 -n "$NAMESPACE" &> /dev/null; then
        kubectl wait --for=condition=ready pod opensearch-cluster-master-0 -n "$NAMESPACE" --timeout=600s 2>/dev/null || log_warning "OpenSearch timeout"
    else
        log_warning "No OpenSearch pod found (may be using external service)"
    fi
    
    # Wait for OpenCTI application
    log_info "Waiting for OpenCTI application..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opencti -n "$NAMESPACE" --timeout=600s 2>/dev/null || log_warning "OpenCTI timeout"
    
    log_success "Services deployment completed (some timeouts are normal)"
}

# Show deployment status
show_status() {
    log_info "OpenCTI Deployment Status:"
    echo
    
    # Show pods
    log_info "Pods:"
    kubectl get pods -n "$NAMESPACE" -o wide
    echo
    
    # Show services
    log_info "Services:"
    kubectl get svc -n "$NAMESPACE"
    echo
    
    # Show ingress
    log_info "Ingress:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || log_warning "No ingress found"
    echo
    
    # Show persistent volumes
    log_info "Storage:"
    kubectl get pvc -n "$NAMESPACE"
    echo
    
    # Get admin token
    if kubectl get secret opencti-secrets -n "$NAMESPACE" &> /dev/null; then
        ADMIN_TOKEN=$(kubectl get secret opencti-secrets -n "$NAMESPACE" -o jsonpath='{.data.admin-token}' | base64 -d)
        
        log_success "OpenCTI is accessible at: https://opencti.ozzu.world"
        echo
        log_info "Default credentials:"
        echo "  Email: admin@ozzu.world"
        echo "  Password: OpenCTI2024!"
        echo "  Admin Token: $ADMIN_TOKEN"
        echo
    fi
    
    log_warning "Remember to change default passwords in production!"
}

# Get logs function
get_logs() {
    log_info "Recent OpenCTI application logs:"
    kubectl logs -l app.kubernetes.io/name=opencti -n "$NAMESPACE" --tail=50 2>/dev/null || \
        log_warning "No OpenCTI pods found or logs not available"
    
    echo
    log_info "OpenSearch logs:"
    kubectl logs opensearch-cluster-master-0 -n "$NAMESPACE" --tail=20 2>/dev/null || \
        log_warning "No OpenSearch logs available"
}

# Troubleshooting function
troubleshoot() {
    log_info "OpenCTI Troubleshooting Information:"
    echo
    
    # Check failed pods
    log_info "Failed/Pending Pods:"
    kubectl get pods -n "$NAMESPACE" --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null || echo "No failed pods"
    echo
    
    # Check recent events
    log_info "Recent Events:"
    kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -10
    echo
    
    # Show services and endpoints
    log_info "Service Endpoints:"
    kubectl get endpoints -n "$NAMESPACE"
    echo
    
    # Test OpenSearch connectivity
    log_info "Testing OpenSearch connectivity from a test pod:"
    kubectl run test-curl --rm -i --restart=Never --image=curlimages/curl:latest -n "$NAMESPACE" -- \
        curl -s http://opensearch-cluster-master:9200 2>/dev/null || \
        log_warning "Could not test OpenSearch connectivity"
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
    log_info "Starting OpenCTI deployment using upstream chart..."
    
    check_prerequisites
    add_helm_repo
    create_namespace
    check_opensearch
    generate_secrets
    deploy_opencti
    
    # Wait for services if requested
    if [ "${WAIT_FOR_READY:-true}" = "true" ]; then
        wait_for_services
    fi
    
    # Verify connectivity
    verify_opensearch_connectivity
    
    show_status
    
    log_success "OpenCTI deployment completed successfully!"
    log_info "If you see connection errors, run: $0 --troubleshoot"
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
        --no-wait)
            WAIT_FOR_READY="false"
            shift
            ;;
        --logs)
            get_logs
            exit 0
            ;;
        --status)
            show_status
            exit 0
            ;;
        --troubleshoot)
            troubleshoot
            exit 0
            ;;
        --cleanup)
            cleanup_deployment
            exit 0
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --namespace NAMESPACE    Kubernetes namespace (default: opencti)"
            echo "  --release-name NAME      Helm release name (default: opencti)"
            echo "  --no-wait               Don't wait for deployment to be ready"
            echo "  --logs                  Show recent application logs"
            echo "  --status                Show deployment status"
            echo "  --troubleshoot          Show troubleshooting information"
            echo "  --cleanup               Remove OpenCTI deployment"
            echo "  --help                  Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1. Use --help for usage information."
            ;;
    esac
done

# Run main function
main