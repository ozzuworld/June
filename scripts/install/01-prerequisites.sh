#!/bin/bash
# June Platform - Phase 1: Prerequisites Installation
# Installs basic system requirements

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

install_prerequisites() {
    log "Phase 1/9: Installing prerequisites..."
    
    # Check if packages are already installed first
    log "Checking existing packages..."
    local missing_packages=()
    local available_packages=()
    
    local required_packages=(
        "curl"
        "wget"
        "git"
        "apt-transport-https"
        "ca-certificates"
        "gnupg"
        "lsb-release"
        "jq"
        "openssl"
        "unzip"
        "software-properties-common"
    )
    
    # Check which packages are missing
    for package in "${required_packages[@]}"; do
        if command -v "$package" &> /dev/null || dpkg -l | grep -q "^ii.*$package "; then
            available_packages+=("$package")
            log "  ✅ $package already available"
        else
            missing_packages+=("$package")
            log "  ❌ $package missing"
        fi
    done
    
    if [ ${#missing_packages[@]} -eq 0 ]; then
        success "All prerequisites already installed"
        return 0
    fi
    
    log "Need to install ${#missing_packages[@]} packages: ${missing_packages[*]}"
    
    # Update package list with better error handling
    log "Updating package list..."
    if ! apt-get update -qq; then
        warn "Package list update failed, trying with verbose output..."
        apt-get update
    fi
    
    # Install missing packages with better error handling
    log "Installing missing packages..."
    log "Command: apt-get install -y ${missing_packages[*]}"
    
    # Try to install packages with verbose output to see any issues
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_packages[@]}"; then
        error "Failed to install packages: ${missing_packages[*]}"
    fi
    
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
    
    # Check system requirements
    log "Checking system status..."
    
    # Check for apt locks
    if pgrep -x "apt" > /dev/null || pgrep -x "apt-get" > /dev/null; then
        warn "apt process is running, waiting for it to finish..."
        while pgrep -x "apt" > /dev/null || pgrep -x "apt-get" > /dev/null; do
            sleep 2
        done
        log "apt process finished"
    fi
    
    # Check disk space
    local available_gb
    available_gb=$(df / | awk 'NR==2 {print int($4/1024/1024)}')
    if [ "$available_gb" -lt 2 ]; then
        error "Insufficient disk space: ${available_gb}GB available, need at least 2GB"
    fi
    log "Disk space check passed: ${available_gb}GB available"
    
    # Check network connectivity
    if ! ping -c 1 8.8.8.8 &>/dev/null; then
        error "No network connectivity - cannot reach external servers"
    fi
    log "Network connectivity check passed"
    
    install_prerequisites
    
    success "Prerequisites installation phase completed"
}

main "$@"