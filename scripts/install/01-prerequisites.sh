#!/bin/bash
# June Platform - Phase 1: Prerequisites Installation
# Installs basic system requirements

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

install_prerequisites() {
    log "Phase 1/9: Installing prerequisites..."
    
    # Update package list quietly
    log "Updating package list..."
    apt-get update -qq
    
    # Install essential packages
    log "Installing essential packages..."
    apt-get install -y \
        curl \
        wget \
        git \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        jq \
        openssl \
        unzip \
        software-properties-common \
        > /dev/null 2>&1
    
    # Verify critical tools are available
    verify_command "curl" "curl is required for downloading components"
    verify_command "wget" "wget is required for downloading components"
    verify_command "git" "git is required for repository operations"
    verify_command "jq" "jq is required for JSON processing"
    verify_command "openssl" "openssl is required for certificate operations"
    
    success "Prerequisites installed"
    
    # Show installed versions for debugging
    log "Installed versions:"
    log "  curl: $(curl --version | head -1)"
    log "  git: $(git --version)"
    log "  jq: $(jq --version)"
    log "  openssl: $(openssl version)"
}

# Main execution
main() {
    log "Starting prerequisites installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    install_prerequisites
    
    success "Prerequisites installation phase completed"
}

main "$@"