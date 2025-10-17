#!/bin/bash

# OpenCTI Deployment Script using Upstream Helm Chart
# This script deploys OpenCTI using the official helm-opencti chart

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
    
    # Deploy using Helm
    if helm list -n "$NAMESPACE" | grep -q "$RELEASE_NAME"; then
        log_info "Upgrading existing OpenCTI deployment..."
        helm upgrade "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$VALUES_FILE" \
            --timeout 15m0s \
            --wait
    else
        log_info "Installing OpenCTI..."
        helm upgrade --install "$RELEASE_NAME" "$CHART_NAME" \
            --namespace "$NAMESPACE" \
            --values "$VALUES_FILE" \
            --timeout 15m0s \
            --wait
    fi
    
    log_success "OpenCTI deployment completed"
}

# Wait for services
wait_for_services() {
    log_info "Waiting for OpenCTI services to be ready..."
    
    # Wait for dependencies first
    log_info "Waiting for Redis..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=redis -n "$NAMESPACE" --timeout=300s
    
    log_info "Waiting for Elasticsearch..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=elasticsearch -n "$NAMESPACE" --timeout=600s
    
    log_info "Waiting for RabbitMQ..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=rabbitmq -n "$NAMESPACE" --timeout=300s
    
    log_info "Waiting for MinIO..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=minio -n "$NAMESPACE" --timeout=300s
    
    # Wait for OpenCTI application
    log_info "Waiting for OpenCTI application..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opencti -n "$NAMESPACE" --timeout=600s
    
    log_success "All services are ready"
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
    kubectl logs -l app.kubernetes.io/name=opencti -n "$NAMESPACE" --tail=20 2>/dev/null || \
        log_warning "No OpenCTI pods found or logs not available"
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
    generate_secrets
    deploy_opencti
    
    # Wait for services if requested
    if [ "${WAIT_FOR_READY:-true}" = "true" ]; then
        wait_for_services
    fi
    
    show_status
    
    log_success "OpenCTI deployment completed successfully!"
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