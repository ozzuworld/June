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
    
    # Add NVIDIA repository with proper Ubuntu 24.04 support
    log "Adding NVIDIA repository..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    
    # Get OS information and determine correct repository path
    . /etc/os-release
    
    # Handle Ubuntu 24.04 Noble specifically
    local repo_path
    if [ "$ID" = "ubuntu" ] && [ "$VERSION_ID" = "24.04" ]; then
        repo_path="ubuntu noble"
        log "Detected Ubuntu 24.04 Noble - using noble codename"
    elif [ "$ID" = "ubuntu" ] && [ -n "$VERSION_CODENAME" ]; then
        repo_path="ubuntu $VERSION_CODENAME"
        log "Using Ubuntu codename: $VERSION_CODENAME"
    else
        # Fallback for other distributions
        repo_path="${ID}${VERSION_ID}"
        log "Using distribution path: $repo_path"
    fi
    
    # Add repository source
    cat > /etc/apt/sources.list.d/nvidia-container-toolkit.list <<EOF
deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/$repo_path /
EOF
    
    # Update package list
    log "Updating package list with NVIDIA repository..."
    if ! apt-get update -qq; then
        warn "Package list update failed, trying with verbose output..."
        apt-get update
    fi
    
    # Install NVIDIA Container Toolkit
    log "Installing NVIDIA Container Toolkit..."
    if ! apt-get install -y nvidia-container-toolkit; then
        # Fallback: try different repository format
        warn "Installation failed, trying alternative repository format..."
        
        # Remove existing repo and try ubuntu/bionic format (more widely supported)
        rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
        
        cat > /etc/apt/sources.list.d/nvidia-container-toolkit.list <<EOF
deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/ubuntu bionic main
EOF
        
        apt-get update -qq
        apt-get install -y nvidia-container-toolkit
    fi
    
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
        warn "nvidia-smi not working - may need reboot to activate drivers"
        return 1
    fi
    
    # Test Docker GPU access
    log "Testing Docker GPU access..."
    if docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi &>/dev/null; then
        success "Docker can access GPU successfully"
    else
        warn "Docker GPU access test failed - may need reboot"
        return 1
    fi
    
    # Check Kubernetes can see GPU (if cluster is ready)
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null; then
        log "Checking Kubernetes GPU detection..."
        sleep 10  # Wait for device plugin to register GPUs
        
        local gpu_nodes
        gpu_nodes=$(kubectl get nodes -o json | jq -r '.items[] | select(.status.capacity."nvidia.com/gpu" != null) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$gpu_nodes" ]; then
            success "Kubernetes detected GPU on nodes: $gpu_nodes"
            kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpus: .status.capacity."nvidia.com/gpu"}' 2>/dev/null || true
        else
            log "Kubernetes has not detected GPUs yet - normal if cluster not ready"
        fi
    fi
    
    return 0
}

handle_reboot_requirement() {
    log "Checking if reboot is required..."
    
    # Check if drivers are loaded but nvidia-smi doesn't work
    if lsmod | grep -q nvidia && ! nvidia-smi &>/dev/null; then
        warn "NVIDIA drivers loaded but not functional - reboot required"
        return 1
    fi
    
    # Check if needrestart indicates kernel upgrade
    if command -v needrestart &>/dev/null; then
        if needrestart -k 2>/dev/null | grep -q "Pending kernel upgrade"; then
            warn "Kernel upgrade detected - reboot recommended"
            return 1
        fi
    fi
    
    # Check if /var/run/reboot-required exists
    if [ -f /var/run/reboot-required ]; then
        warn "System indicates reboot required"
        return 1
    fi
    
    return 0
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
    if check_nvidia_driver_status && verify_gpu_setup; then
        log "NVIDIA drivers already working properly"
    else
        install_nvidia_drivers
        
        # Check if reboot is needed after driver installation
        if ! handle_reboot_requirement; then
            warn "=================================================="
            warn "REBOOT REQUIRED: NVIDIA drivers installed but not active"
            warn "=================================================="
            warn "Please reboot the system and re-run the installer:"
            warn "  sudo reboot"
            warn "After reboot:"
            warn "  bash scripts/install-orchestrator.sh --skip 01-prerequisites 02-docker 02.5-gpu"
            warn "=================================================="
            
            # Still try to install container toolkit for completeness
            log "Installing container toolkit anyway (will be ready after reboot)..."
        fi
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
}

main "$@"