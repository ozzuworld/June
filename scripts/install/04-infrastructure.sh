#!/bin/bash
# June Platform - Phase 4: Infrastructure Installation
# Installs ingress-nginx, cert-manager, and creates ClusterIssuer

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

install_ingress_nginx() {
    log "Installing ingress-nginx..."
    
    # Check if ingress-nginx is already installed
    if kubectl get namespace ingress-nginx &> /dev/null; then
        success "ingress-nginx already installed"
        return 0
    fi
    
    # Install ingress-nginx
    log "Downloading and applying ingress-nginx manifest..."
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml > /dev/null 2>&1
    
    # Wait a bit for the deployment to be created
    sleep 10
    
    # Enable host networking for bare metal deployment
    log "Configuring ingress-nginx for host networking..."
    kubectl patch deployment ingress-nginx-controller -n ingress-nginx \
        --type='json' \
        -p='[{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},{"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}]' \
        > /dev/null 2>&1
    
    # Wait for ingress-nginx to be ready
    log "Waiting for ingress-nginx to be ready..."
    wait_for_deployment "ingress-nginx-controller" "ingress-nginx" 300
    
    success "ingress-nginx installed and configured"
}

install_cert_manager() {
    log "Installing cert-manager..."
    
    # Check if cert-manager is already installed
    if kubectl get namespace cert-manager &> /dev/null; then
        success "cert-manager already installed"
        return 0
    fi
    
    # Install cert-manager
    log "Downloading and applying cert-manager manifest..."
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml > /dev/null 2>&1
    
    # Wait for cert-manager deployments to be available
    log "Waiting for cert-manager deployments..."
    wait_for_deployment "cert-manager" "cert-manager" 300
    wait_for_deployment "cert-manager-cainjector" "cert-manager" 300
    wait_for_deployment "cert-manager-webhook" "cert-manager" 300
    
    success "cert-manager installed"
}

wait_for_cert_manager_crds() {
    log "Waiting for cert-manager CRDs to be ready..."
    
    local timeout=180
    local counter=0
    local crds=("clusterissuers.cert-manager.io" "certificates.cert-manager.io" "certificaterequests.cert-manager.io" "issuers.cert-manager.io")
    
    while [ $counter -lt $timeout ]; do
        local all_ready=true
        
        for crd in "${crds[@]}"; do
            if ! kubectl get crd "$crd" &> /dev/null; then
                all_ready=false
                break
            fi
        done
        
        # Additional check: ensure cert-manager can process resources
        if [ "$all_ready" = "true" ] && kubectl get clusterissuers &> /dev/null; then
            success "cert-manager CRDs ready and functional"
            return 0
        fi
        
        sleep 3
        counter=$((counter + 3))
        
        if [ $((counter % 30)) -eq 0 ]; then
            log "Still waiting for cert-manager CRDs... ($counter/${timeout}s)"
            kubectl get pods -n cert-manager --no-headers 2>/dev/null | awk '{print $1 ": " $3}' | head -3
        fi
    done
    
    warn "cert-manager CRDs took longer than expected, checking status..."
    log "Checking cert-manager pods status:"
    kubectl get pods -n cert-manager
    log "Checking cert-manager logs:"
    kubectl logs -n cert-manager deployment/cert-manager --tail=10 || true
    
    # Don't fail, just warn - sometimes it works anyway
    warn "Continuing despite CRD timeout..."
}

setup_cloudflare_secret() {
    log "Setting up Cloudflare API token secret..."
    
    # Validate that CLOUDFLARE_TOKEN is set
    if [ -z "$CLOUDFLARE_TOKEN" ]; then
        error "CLOUDFLARE_TOKEN environment variable is not set"
    fi
    
    # Create Cloudflare secret for DNS challenges
    kubectl create secret generic cloudflare-api-token \
        --from-literal=api-token="$CLOUDFLARE_TOKEN" \
        --namespace=cert-manager \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    success "Cloudflare API token secret created"
}

setup_cluster_issuer() {
    log "Creating Let's Encrypt ClusterIssuer..."
    
    # Validate that required environment variables are set
    if [ -z "$DOMAIN" ]; then
        error "DOMAIN environment variable is not set"
    fi
    
    if [ -z "$LETSENCRYPT_EMAIL" ]; then
        error "LETSENCRYPT_EMAIL environment variable is not set"
    fi
    
    # Create ClusterIssuer for Let's Encrypt
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsNames:
        - "$DOMAIN"
        - "*.$DOMAIN"
EOF
    
    success "ClusterIssuer created for domain: $DOMAIN"
}

setup_storage() {
    log "Setting up local storage for persistent volumes..."
    
    # Create directory for PostgreSQL data
    mkdir -p /opt/june-postgresql-data
    chmod 755 /opt/june-postgresql-data
    
    # Create StorageClass for local storage
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF
    
    success "Local storage configured"
}

verify_infrastructure() {
    log "Verifying infrastructure installation..."
    
    # Check ingress-nginx
    verify_namespace "ingress-nginx"
    verify_k8s_resource "deployment" "ingress-nginx-controller" "ingress-nginx"
    
    # Check cert-manager
    verify_namespace "cert-manager"
    verify_k8s_resource "deployment" "cert-manager" "cert-manager"
    verify_k8s_resource "deployment" "cert-manager-cainjector" "cert-manager"
    verify_k8s_resource "deployment" "cert-manager-webhook" "cert-manager"
    
    # Check ClusterIssuer
    verify_k8s_resource "clusterissuer" "letsencrypt-prod" "default"
    
    # Check StorageClass
    verify_k8s_resource "storageclass" "local-storage" "default"
    
    success "Infrastructure verification completed"
    
    # Show infrastructure status
    log "Infrastructure status:"
    kubectl get pods -n ingress-nginx
    kubectl get pods -n cert-manager
    kubectl get clusterissuer
}

# Main execution
main() {
    log "Starting infrastructure installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify Kubernetes is running
    verify_command "kubectl" "kubectl must be available"
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster must be running"
    fi
    
    install_ingress_nginx
    install_cert_manager
    wait_for_cert_manager_crds
    setup_cloudflare_secret
    setup_cluster_issuer
    setup_storage
    verify_infrastructure
    
    success "Infrastructure installation phase completed"
}

main "$@"