#!/bin/bash
# June Platform - Phase 2.5: GPU Detection
# Detects GPU availability - GPU Operator will handle driver installation

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

detect_nvidia_gpu() {
    log "Detecting NVIDIA GPU hardware..."
    
    if lspci | grep -i nvidia | grep -i vga &>/dev/null; then
        local gpu_info
        gpu_info=$(lspci | grep -i nvidia | grep -i vga | head -1)
        success "NVIDIA GPU detected: $gpu_info"
        return 0
    else
        log "No NVIDIA GPU detected in system"
        return 1
    fi
}

check_nvidia_driver_status() {
    log "Checking if NVIDIA drivers are already installed..."
    
    if command -v nvidia-smi &>/dev/null; then
        if nvidia-smi &>/dev/null; then
            success "NVIDIA drivers already installed and working"
            nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
            return 0
        fi
    fi
    
    log "NVIDIA drivers not yet installed (GPU Operator will handle this)"
    return 1
}

# Main execution
main() {
    log "Starting GPU detection phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Detect GPU hardware
    if detect_nvidia_gpu; then
        log "GPU hardware detected"
        export GPU_AVAILABLE=true
        
        # Check if drivers are already installed
        if check_nvidia_driver_status; then
            log "Drivers already present - GPU Operator will manage them"
        else
            log "No drivers installed yet - GPU Operator will install them in phase 03.5"
        fi
        
        # Store GPU availability for later phases
        echo "true" > /tmp/.june_gpu_available
        
        success "GPU detection completed - configuration will happen in GPU Operator phase"
    else
        log "No NVIDIA GPU detected, skipping GPU setup"
        export GPU_AVAILABLE=false
        echo "false" > /tmp/.june_gpu_available
        
        success "GPU detection phase completed (no GPU found)"
    fi
}

main "$@"