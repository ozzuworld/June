#!/bin/bash
# June Platform - Phase 3: Kubernetes Installation
# Installs and configures Kubernetes cluster

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

setup_kernel_modules() {
    log "Setting up kernel modules for Kubernetes..."
    
    # Load required kernel modules
    modprobe br_netfilter
    modprobe overlay
    
    # Make kernel modules persistent
    cat > /etc/modules-load.d/k8s.conf << EOF
br_netfilter
overlay
EOF
    
    success "Kernel modules configured"
}

setup_sysctl() {
    log "Configuring sysctl parameters for Kubernetes..."
    
    # Set required sysctl parameters
    cat > /etc/sysctl.d/k8s.conf << EOF
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
    
    # Apply sysctl parameters
    sysctl --system > /dev/null 2>&1
    
    success "Sysctl parameters configured"
}

install_kubernetes_packages() {
    log "Installing Kubernetes packages..."
    
    # Add Kubernetes apt repository
    mkdir -p /etc/apt/keyrings
    
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    
    # Update package list with new repository
    apt-get update -qq
    
    # Install Kubernetes components
    log "Installing kubelet, kubeadm, and kubectl..."
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    
    # Hold packages to prevent unexpected upgrades
    apt-mark hold kubelet kubeadm kubectl
    
    # Verify installations
    verify_command "kubelet" "kubelet installation failed"
    verify_command "kubeadm" "kubeadm installation failed"
    verify_command "kubectl" "kubectl installation failed"
    
    success "Kubernetes packages installed"
    
    # Show installed versions
    log "Installed versions:"
    log "  kubelet: $(kubelet --version)"
    log "  kubeadm: $(kubeadm version -o short)"
    log "  kubectl: $(kubectl version --client -o yaml | grep gitVersion | cut -d' ' -f4)"
}

initialize_cluster() {
    log "Initializing Kubernetes cluster..."
    
    # Check if cluster is already initialized
    if kubectl cluster-info &> /dev/null; then
        success "Kubernetes cluster already running"
        return 0
    fi
    
    # Get the internal IP address
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    log "Using internal IP: $INTERNAL_IP"
    
    # Initialize the cluster
    log "Running kubeadm init (this may take several minutes)..."
    kubeadm init \
        --pod-network-cidr=10.244.0.0/16 \
        --apiserver-advertise-address="$INTERNAL_IP" \
        --cri-socket=unix:///var/run/containerd/containerd.sock \
        > /dev/null 2>&1
    
    success "Kubernetes cluster initialized"
}

setup_kubectl() {
    log "Setting up kubectl configuration..."
    
    # Setup kubectl for root user
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    # Verify kubectl can connect to cluster
    if kubectl cluster-info &> /dev/null; then
        success "kubectl configured successfully"
    else
        error "kubectl configuration failed"
    fi
    
    # Show cluster info
    log "Cluster information:"
    kubectl cluster-info
}

install_cni() {
    log "Installing Flannel CNI plugin..."
    
    # Download and apply Flannel manifest
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    
    # Wait for Flannel to be ready
    log "Waiting for Flannel pods to be ready..."
    wait_for_pods "app=flannel" "kube-flannel" 300
    
    success "Flannel CNI installed"
}

setup_single_node() {
    log "Configuring single-node cluster..."
    
    # Remove taints to allow pods to run on control plane
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    
    success "Single-node cluster configured"
}

wait_for_cluster() {
    log "Waiting for cluster to be fully ready..."
    
    # Wait for all nodes to be ready
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    
    # Wait for core system pods to be ready
    wait_for_pods "component=kube-apiserver" "kube-system" 300
    wait_for_pods "component=kube-controller-manager" "kube-system" 300
    wait_for_pods "component=kube-scheduler" "kube-system" 300
    wait_for_pods "component=etcd" "kube-system" 300
    
    success "Kubernetes cluster is ready"
    
    # Show cluster status
    log "Cluster status:"
    kubectl get nodes -o wide
    kubectl get pods -n kube-system
}

# Main execution
main() {
    log "Starting Kubernetes installation phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify Docker is installed and running
    verify_command "docker" "Docker must be installed before Kubernetes"
    verify_service "docker" "Docker must be running before Kubernetes installation"
    
    setup_kernel_modules
    setup_sysctl
    install_kubernetes_packages
    initialize_cluster
    setup_kubectl
    install_cni
    setup_single_node
    wait_for_cluster
    
    success "Kubernetes installation phase completed"
}

main "$@"