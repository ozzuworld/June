#!/bin/bash
# June Platform - Phase 2: Docker Installation
# Installs and configures Docker with containerd

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname "$(dirname "$(dirname "$0")")")"}" 

install_docker() {
    log "Phase 2/9: Installing Docker..."
    
    # Check if Docker is already installed and running
    if command -v docker &> /dev/null && docker version &> /dev/null; then
        success "Docker already installed and running"
        docker --version
        return 0
    fi
    
    log "Installing Docker from official repository..."
    
    # Download and run Docker installation script
    curl -fsSL https://get.docker.com | bash > /dev/null 2>&1
    
    # Verify Docker was installed
    verify_command "docker" "Docker installation failed"
    
    log "Configuring containerd for Kubernetes..."
    
    # Stop containerd to modify configuration
    systemctl stop containerd
    
    # Create containerd config directory if it doesn't exist
    mkdir -p /etc/containerd
    
    # Generate default containerd config
    containerd config default > /etc/containerd/config.toml
    
    # Enable SystemdCgroup for Kubernetes compatibility
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    
    # Start and enable containerd
    systemctl start containerd
    systemctl enable containerd > /dev/null 2>&1
    
    # Verify containerd is running
    verify_service "containerd" "containerd failed to start"
    
    # Start and enable Docker
    systemctl start docker
    systemctl enable docker > /dev/null 2>&1
    
    # Verify Docker is running
    verify_service "docker" "Docker failed to start"
    
    success "Docker installed and configured"
    
    # Show Docker info for debugging
    log "Docker version: $(docker --version)"
    log "Containerd version: $(containerd --version | head -1)"
    
    # Test Docker functionality
    log "Testing Docker functionality..."
    if docker run --rm hello-world > /dev/null 2>&1; then
        success "Docker test completed successfully"
    else
        warn "Docker test failed, but Docker appears to be installed"
    fi
}

# Configure Docker for optimal Kubernetes usage
configure_docker() {
    log "Configuring Docker for Kubernetes..."
    
    # Create Docker daemon configuration
    mkdir -p /etc/docker
    
    cat > /etc/docker/daemon.json << EOF
{
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF
    
    # Restart Docker to apply configuration
    systemctl restart docker
    
    # Verify Docker is still running after configuration
    verify_service "docker" "Docker failed to restart after configuration"
    
    success "Docker configured for Kubernetes"
}

# Main execution
main() {
    log "Starting Docker installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    install_docker
    configure_docker
    
    success "Docker installation phase completed"
}

main "$@"