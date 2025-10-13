#!/bin/bash
# June Platform - Phase 5: Helm Installation
# Installs Helm package manager for Kubernetes

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

install_helm() {
    log "Phase 5/9: Installing Helm..."
    
    # Check if Helm is already installed
    if command -v helm &> /dev/null; then
        success "Helm already installed"
        log "Helm version: $(helm version --short)"
        return 0
    fi
    
    log "Downloading and installing Helm..."
    
    # Download and install Helm using the official script
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    
    # Verify Helm installation
    verify_command "helm" "Helm installation failed"
    
    success "Helm installed"
    log "Helm version: $(helm version --short)"
}

setup_helm_repos() {
    log "Setting up common Helm repositories..."
    
    # Add common repositories that will be used by June Platform
    local repos=(
        "bitnami https://charts.bitnami.com/bitnami"
        "ingress-nginx https://kubernetes.github.io/ingress-nginx"
        "cert-manager https://charts.jetstack.io"
    )
    
    for repo in "${repos[@]}"; do
        local name=$(echo $repo | cut -d' ' -f1)
        local url=$(echo $repo | cut -d' ' -f2)
        
        log "Adding Helm repository: $name"
        
        # Try to add the repository with retry logic
        local retries=3
        local count=0
        while [ $count -lt $retries ]; do
            if helm repo add "$name" "$url" > /dev/null 2>&1; then
                break
            fi
            count=$((count + 1))
            if [ $count -eq $retries ]; then
                warn "Failed to add Helm repository: $name"
                continue 2
            fi
            log "Retrying to add repository $name (attempt $((count + 1))/$retries)..."
            sleep 5
        done
    done
    
    success "Common Helm repositories added"
}

update_helm_repos() {
    log "Updating Helm repositories..."
    
    # Update all repositories with retry logic
    local retries=3
    local count=0
    while [ $count -lt $retries ]; do
        if helm repo update > /dev/null 2>&1; then
            success "Helm repositories updated"
            return 0
        fi
        count=$((count + 1))
        if [ $count -eq $retries ]; then
            warn "Failed to update Helm repositories after $retries attempts"
            return 1
        fi
        log "Retrying repository update (attempt $((count + 1))/$retries)..."
        sleep 5
    done
}

list_helm_repos() {
    log "Configured Helm repositories:"
    helm repo list 2>/dev/null || log "No repositories configured"
}

verify_helm() {
    log "Verifying Helm installation..."
    
    # Check Helm version
    verify_command "helm" "Helm must be installed"
    
    # Test Helm connectivity to Kubernetes
    if helm list > /dev/null 2>&1; then
        success "Helm can connect to Kubernetes cluster"
    else
        error "Helm cannot connect to Kubernetes cluster"
    fi
    
    # Show Helm environment
    log "Helm environment:"
    helm env
}

# Main execution
main() {
    log "Starting Helm installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify Kubernetes is running
    verify_command "kubectl" "kubectl must be available"
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster must be running"
    fi
    
    install_helm
    setup_helm_repos
    update_helm_repos
    list_helm_repos
    verify_helm
    
    success "Helm installation phase completed"
}

main "$@"