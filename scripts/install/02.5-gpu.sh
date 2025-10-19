#!/bin/bash
# Phase 2.5: GPU Detection Only
# Let GPU Operator handle driver installation

detect_nvidia_gpu() {
    log "Detecting NVIDIA GPU hardware..."
    if lspci | grep -i nvidia | grep -i vga &>/dev/null; then
        success "NVIDIA GPU detected"
        export GPU_AVAILABLE=true
        return 0
    else
        log "No NVIDIA GPU detected"
        export GPU_AVAILABLE=false
        return 1
    fi
}

main() {
    log "GPU Detection Phase..."
    
    if detect_nvidia_gpu; then
        # Just detect, don't install anything
        success "GPU will be configured by GPU Operator in later phase"
    else
        log "Skipping GPU setup - no GPU found"
    fi
}

main "$@"