#!/bin/bash
# June Platform - Phase 2.5: GPU Setup
# Detects and installs NVIDIA GPU drivers and container toolkit

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

detect_nvidia_gpu() {
    log "Detecting NVIDIA GPU hardware..."
    
    # Check if NVIDIA GPU is present via PCI
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
    log "Checking NVIDIA driver status..."
    
    if command -v nvidia-smi &>/dev/null; then
        if nvidia-smi &>/dev/null; then
            success "NVIDIA drivers already installed and working"
            nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
            return 0
        else
            warn "nvidia-smi found but not working properly"
            return 1
        fi
    else
        log "nvidia-smi not found - drivers not installed"
        return 1
    fi
}

install_nvidia_drivers() {
    log "Installing NVIDIA drivers..."
    
    # Update package list
    log "Updating package repositories..."
    apt-get update -qq
    
    # Install ubuntu-drivers-common for automatic detection
    log "Installing driver detection tools..."
    apt-get install -y ubuntu-drivers-common
    
    # Show available drivers
    log "Available NVIDIA drivers:"
    ubuntu-drivers devices
    
    # Install recommended driver
    log "Installing recommended NVIDIA driver..."
    if ubuntu-drivers autoinstall; then
        success "NVIDIA drivers installed successfully"
    else
        # Fallback to manual driver installation
        warn "Automatic installation failed, trying manual installation..."
        
        # Try to install a recent stable driver
        local drivers=("nvidia-driver-535" "nvidia-driver-550" "nvidia-driver-470")
        local installed=false
        
        for driver in "${drivers[@]}"; do
            if apt-cache show "$driver" &>/dev/null; then
                log "Installing $driver..."
                if apt-get install -y "$driver"; then
                    installed=true
                    success "Installed $driver successfully"
                    break
                fi
            fi
        done
        
        if [ "$installed" = "false" ]; then
            error "Failed to install any NVIDIA driver"
        fi
    fi
    
    # Install nvidia-utils for nvidia-smi
    log "Installing NVIDIA utilities..."
    apt-get install -y nvidia-utils-* 2>/dev/null || {
        # Try specific versions if wildcard fails
        apt-get install -y nvidia-utils-535 || 
        apt-get install -y nvidia-utils-550 || 
        apt-get install -y nvidia-utils-470 || 
        warn "Could not install nvidia-utils, nvidia-smi may not be available"
    }
}

install_nvidia_container_toolkit() {
    log "Installing NVIDIA Container Toolkit for Kubernetes..."
    
    # Add NVIDIA repository
    log "Adding NVIDIA repository..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    # Add repository source
    . /etc/os-release
    echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/${ID}${VERSION_ID} /" > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    
    # Update package list
    apt-get update -qq
    
    # Install NVIDIA Container Toolkit
    log "Installing NVIDIA Container Toolkit..."
    apt-get install -y nvidia-container-toolkit
    
    # Configure Docker runtime
    log "Configuring Docker to use NVIDIA runtime..."
    nvidia-ctk runtime configure --runtime=docker
    
    # Restart Docker to apply changes
    log "Restarting Docker service..."
    systemctl restart docker
    
    success "NVIDIA Container Toolkit installed and configured"
}

install_nvidia_device_plugin() {
    log "Installing NVIDIA Device Plugin for Kubernetes..."
    
    # Apply NVIDIA device plugin
    kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.3/nvidia-device-plugin.yml
    
    # Wait for device plugin to be ready
    log "Waiting for NVIDIA device plugin to start..."
    wait_for_pods "name=nvidia-device-plugin-ds" "kube-system" 120
    
    success "NVIDIA Device Plugin installed"
}

verify_gpu_setup() {
    log "Verifying GPU setup..."
    
    # Test nvidia-smi
    if nvidia-smi &>/dev/null; then
        success "nvidia-smi working correctly"
        nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    else
        error "nvidia-smi not working after installation"
    fi
    
    # Test Docker GPU access
    log "Testing Docker GPU access..."
    if docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi &>/dev/null; then
        success "Docker can access GPU successfully"
    else
        warn "Docker GPU access test failed - may need reboot"
    fi
    
    # Check Kubernetes can see GPU
    log "Checking Kubernetes GPU detection..."
    sleep 10  # Wait for device plugin to register GPUs
    
    local gpu_nodes
    gpu_nodes=$(kubectl get nodes -o json | jq -r '.items[] | select(.status.capacity."nvidia.com/gpu" != null) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$gpu_nodes" ]; then
        success "Kubernetes detected GPU on nodes: $gpu_nodes"
        kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpus: .status.capacity."nvidia.com/gpu"}' 2>/dev/null || true
    else
        warn "Kubernetes has not detected GPUs yet - may need time or reboot"
    fi
}

# Main execution
main() {
    log "Starting GPU setup phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Skip if no NVIDIA GPU detected
    if ! detect_nvidia_gpu; then
        log "No NVIDIA GPU detected, skipping GPU setup"
        success "GPU setup phase completed (no GPU found)"
        return 0
    fi
    
    # Check if drivers are already working
    if check_nvidia_driver_status; then
        log "NVIDIA drivers already working, checking container toolkit..."
    else
        install_nvidia_drivers
        log "NVIDIA drivers installed - system will need reboot to activate"
    fi
    
    # Install container toolkit if Docker is available
    if command -v docker &>/dev/null; then
        install_nvidia_container_toolkit
    else
        log "Docker not found yet, skipping container toolkit (will install after Docker phase)"
    fi
    
    # Install device plugin if Kubernetes is available
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null; then
        install_nvidia_device_plugin
        verify_gpu_setup
    else
        log "Kubernetes not ready yet, will install device plugin in later phase"
    fi
    
    success "GPU setup phase completed"
    
    # Check if reboot is needed
    if ! nvidia-smi &>/dev/null && lspci | grep -i nvidia | grep -i vga &>/dev/null; then
        warn "GPU drivers installed but not active - system reboot recommended"
        warn "You may want to reboot and re-run the installation to enable GPU services"
    fi
}

main "$@"