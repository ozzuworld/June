#!/bin/bash
# June Platform - Phase 5: Helm Installation
# Installs Helm package manager for Kubernetes with fallback methods

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

cleanup_stale_nvidia_repo() {
    # Defensive: remove stale NVIDIA repo entries that can break apt on Ubuntu Noble
    if [ -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]; then
        if ! grep -q 'https://nvidia.github.io/libnvidia-container/stable/deb/ubuntu noble' /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null; then
            warn "Removing stale NVIDIA repo causing apt failures..."
            rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
        fi
    fi
}

install_helm_official() {
    log "Attempting official Helm installation method..."
    
    # Test if get.helm.sh is accessible
    if curl -fsSL https://get.helm.sh/helm-latest-version >/dev/null 2>&1; then
        log "Official Helm CDN is accessible, using official installer..."
        curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
        return 0
    else
        warn "Official Helm CDN (get.helm.sh) is not accessible"
        return 1
    fi
}

install_helm_github() {
    log "Attempting GitHub releases installation method..."
    
    # Get latest version from GitHub API
    if curl -s https://api.github.com/repos/helm/helm/releases/latest >/dev/null 2>&1; then
        local helm_version
        helm_version=$(curl -s https://api.github.com/repos/helm/helm/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
        
        if [ -n "$helm_version" ]; then
            log "Latest Helm version from GitHub: $helm_version"
            local download_url="https://github.com/helm/helm/releases/download/${helm_version}/helm-${helm_version}-linux-amd64.tar.gz"
            
            local temp_dir
            temp_dir=$(mktemp -d)
            
            log "Downloading Helm from GitHub releases..."
            if curl -L "$download_url" -o "$temp_dir/helm.tar.gz" 2>/dev/null; then
                if tar -zxf "$temp_dir/helm.tar.gz" -C "$temp_dir" 2>/dev/null; then
                    if cp "$temp_dir/linux-amd64/helm" /usr/local/bin/helm; then
                        chmod +x /usr/local/bin/helm
                        rm -rf "$temp_dir"
                        log "Helm installed from GitHub releases"
                        return 0
                    fi
                fi
            fi
            rm -rf "$temp_dir"
        fi
    fi
    
    warn "GitHub releases method failed"
    return 1
}

install_helm_snap() {
    log "Attempting snap installation method..."
    
    if command -v snap >/dev/null 2>&1; then
        log "Snap is available, installing Helm..."
        if snap install helm --classic >/dev/null 2>&1; then
            log "Helm installed via snap"
            return 0
        fi
    fi
    
    warn "Snap installation method failed"
    return 1
}

install_helm_apt() {
    log "Attempting APT installation method..."
    
    # Try to add Helm APT repository
    if curl -fsSL https://baltocdn.com/helm/signing.asc 2>/dev/null | gpg --dearmor 2>/dev/null | tee /usr/share/keyrings/helm.gpg > /dev/null 2>&1; then
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | tee /etc/apt/sources.list.d/helm-stable-debian.list >/dev/null
        
        if apt-get update >/dev/null 2>&1 && apt-get install helm -y >/dev/null 2>&1; then
            log "Helm installed via APT"
            return 0
        fi
    fi
    
    warn "APT installation method failed"
    return 1
}

install_helm() {
    log "Phase 5/9: Installing Helm..."
    
    # Check if Helm is already installed
    if command -v helm >/dev/null 2>&1; then
        success "Helm already installed"
        log "Helm version: $(helm version --short 2>/dev/null || helm version 2>/dev/null || echo 'Unknown version')"
        return 0
    fi
    
    log "Downloading and installing Helm with fallback methods..."
    
    # Defensive cleanup of stale repos that could break curl/apt in this phase
    cleanup_stale_nvidia_repo
    
    # Try multiple installation methods in order of preference
    local methods=(
        "install_helm_official"
        "install_helm_github" 
        "install_helm_snap"
        "install_helm_apt"
    )
    
    for method in "${methods[@]}"; do
        log "Trying installation method: ${method#install_helm_}"
        if $method; then
            break
        fi
        warn "Method ${method#install_helm_} failed, trying next method..."
    done
    
    # Verify Helm installation
    verify_command "helm" "All Helm installation methods failed"
    
    success "Helm installed successfully"
    log "Helm version: $(helm version --short 2>/dev/null || helm version 2>/dev/null || echo 'Version check failed')"
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
    helm env 2>/dev/null || log "Helm environment not available"
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