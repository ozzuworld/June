#!/bin/bash
# scripts/setup/setup-ingress-nginx.sh
# Automated ingress-nginx setup with environment detection
# 
# This script:
# 1. Detects if running on cloud (AWS/GCP/Azure) or bare metal/VM
# 2. Installs ingress-nginx with correct configuration
# 3. Enables hostNetwork for bare metal (ports 80/443 directly on host)
# 4. Verifies installation and provides access information
#
# Usage:
#   ./scripts/setup/setup-ingress-nginx.sh              # Normal install
#   FORCE_REINSTALL=true ./scripts/setup/setup-ingress-nginx.sh  # Force reinstall

set -e

echo "🌐 Ingress-Nginx Automated Setup"
echo "================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

# Function to detect environment
detect_environment() {
    log_info "Detecting environment..."
    
    # Check for AWS
    if curl -s --max-time 2 http://169.254.169.254/latest/meta-data/ >/dev/null 2>&1; then
        log_success "AWS detected"
        return 0  # Cloud
    fi
    
    # Check for GCP
    if curl -s --max-time 2 -H "Metadata-Flavor: Google" http://metadata.google.internal >/dev/null 2>&1; then
        log_success "GCP detected"
        return 0  # Cloud
    fi
    
    # Check for Azure
    if curl -s --max-time 2 -H "Metadata: true" http://169.254.169.254/metadata/instance >/dev/null 2>&1; then
        log_success "Azure detected"
        return 0  # Cloud
    fi
    
    log_info "Bare metal/VM environment detected"
    return 1  # Bare metal
}

# Function to check if ingress-nginx is installed
is_installed() {
    kubectl get namespace ingress-nginx >/dev/null 2>&1
}

# Function to check if hostNetwork is enabled
has_hostnetwork() {
    local host_net=$(kubectl get deployment ingress-nginx-controller -n ingress-nginx -o jsonpath='{.spec.template.spec.hostNetwork}' 2>/dev/null || echo "false")
    [ "$host_net" = "true" ]
}

# Function to install for cloud environment
install_cloud() {
    log_info "Installing for cloud environment..."
    
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/cloud/deploy.yaml
    
    log_info "Waiting for ingress controller pods..."
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=300s || {
        log_warning "Controller taking longer than expected"
        kubectl get pods -n ingress-nginx
    }
    
    log_info "Waiting for LoadBalancer IP..."
    for i in {1..60}; do
        EXTERNAL_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
        if [ -n "$EXTERNAL_IP" ]; then
            log_success "LoadBalancer IP assigned: $EXTERNAL_IP"
            return 0
        fi
        echo -n "."
        sleep 5
    done
    
    log_warning "LoadBalancer IP not assigned after 5 minutes"
    log_info "This is normal for some cloud environments - checking alternative methods"
    
    EXTERNAL_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    if [ -n "$EXTERNAL_IP" ]; then
        log_success "LoadBalancer hostname: $EXTERNAL_IP"
    fi
}

# Function to install for bare metal environment
install_baremetal() {
    log_info "Installing for bare metal/VM environment..."
    
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml
    
    log_info "Waiting for initial deployment..."
    sleep 15
    
    log_info "Enabling hostNetwork mode (allows direct port 80/443 access)..."
    kubectl patch deployment ingress-nginx-controller \
        -n ingress-nginx \
        --type='json' \
        -p='[
            {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
            {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
        ]'
    
    log_info "Waiting for controller to restart with new configuration..."
    kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s
    
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    log_success "Ingress ready on: $EXTERNAL_IP"
}

# Function to fix existing installation
fix_baremetal() {
    log_info "Fixing existing installation for bare metal..."
    
    if has_hostnetwork; then
        log_success "hostNetwork already enabled"
        return 0
    fi
    
    log_info "Enabling hostNetwork mode..."
    kubectl patch deployment ingress-nginx-controller \
        -n ingress-nginx \
        --type='json' \
        -p='[
            {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
            {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
        ]'
    
    log_info "Waiting for controller to restart..."
    kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s
    
    log_success "hostNetwork enabled"
}

# Function to verify installation
verify_installation() {
    log_info "Verifying installation..."
    
    # Check namespace
    if ! kubectl get namespace ingress-nginx >/dev/null 2>&1; then
        log_error "ingress-nginx namespace not found"
        return 1
    fi
    
    # Check controller pod
    local controller_ready=$(kubectl get pods -n ingress-nginx \
        -l app.kubernetes.io/component=controller \
        -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
    
    if [ "$controller_ready" != "True" ]; then
        log_error "Controller pod not ready"
        kubectl get pods -n ingress-nginx
        return 1
    fi
    
    log_success "Controller pod is ready"
    
    # Show configuration
    echo ""
    echo "📊 Ingress Configuration:"
    kubectl get pods,svc -n ingress-nginx
    
    return 0
}

# Function to show access information
show_access_info() {
    echo ""
    echo "═══════════════════════════════════════════"
    log_success "Ingress-Nginx Setup Complete!"
    echo "═══════════════════════════════════════════"
    echo ""
    
    if detect_environment; then
        # Cloud environment
        LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
        LB_HOST=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
        
        echo "🌐 Access Information:"
        if [ -n "$LB_IP" ]; then
            echo "   External IP: $LB_IP"
            echo ""
            echo "🧪 Test with:"
            echo "   curl -H 'Host: your-domain.com' http://$LB_IP/"
        elif [ -n "$LB_HOST" ]; then
            echo "   LoadBalancer Hostname: $LB_HOST"
            echo ""
            echo "🧪 Test with:"
            echo "   curl -H 'Host: your-domain.com' http://$LB_HOST/"
        else
            echo "   LoadBalancer IP: Pending (check status later)"
        fi
    else
        # Bare metal environment
        EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
        
        echo "🌐 Access Information:"
        echo "   External IP: $EXTERNAL_IP"
        echo "   Ports: 80 (HTTP), 443 (HTTPS)"
        echo "   Mode: hostNetwork (direct port access)"
        echo ""
        echo "🧪 Test with:"
        echo "   curl -H 'Host: api.allsafe.world' http://$EXTERNAL_IP/healthz"
        echo "   curl -H 'Host: idp.allsafe.world' http://$EXTERNAL_IP/"
    fi
    
    echo ""
    echo "📋 Next Steps:"
    echo "   1. Apply your ingress resources: kubectl apply -f k8s/ingress.yaml"
    echo "   2. Update DNS to point your domains to the external IP"
    echo "   3. Configure TLS/SSL certificates (optional)"
    echo ""
    echo "🔍 Useful Commands:"
    echo "   • Check status:  kubectl get pods,svc -n ingress-nginx"
    echo "   • View logs:     kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller"
    echo "   • List ingress:  kubectl get ingress -A"
    echo ""
}

# Main execution
main() {
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl first."
        exit 1
    fi
    
    # Check cluster connectivity
    if ! kubectl cluster-info >/dev/null 2>&1; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    log_success "Connected to Kubernetes cluster"
    
    # Check if force reinstall
    if [ "${FORCE_REINSTALL:-false}" = "true" ] && is_installed; then
        log_warning "FORCE_REINSTALL=true - removing existing installation"
        kubectl delete namespace ingress-nginx
        sleep 5
    fi
    
    # Detect environment
    IS_CLOUD=false
    if detect_environment; then
        IS_CLOUD=true
    fi
    
    # Install or fix
    if is_installed; then
        log_info "ingress-nginx already installed"
        
        # For bare metal, ensure hostNetwork is enabled
        if [ "$IS_CLOUD" = false ]; then
            fix_baremetal
        fi
    else
        log_info "Installing ingress-nginx..."
        
        if [ "$IS_CLOUD" = true ]; then
            install_cloud
        else
            install_baremetal
        fi
    fi
    
    # Verify
    if verify_installation; then
        show_access_info
        exit 0
    else
        log_error "Installation verification failed"
        echo ""
        echo "Debug information:"
        kubectl get all -n ingress-nginx
        echo ""
        kubectl describe pods -n ingress-nginx -l app.kubernetes.io/component=controller | tail -50
        exit 1
    fi
}

# Run main function
main "$@"