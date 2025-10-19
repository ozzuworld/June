#!/bin/bash
# June Platform - Phase 3: Kubernetes Installation
# Installs and configures Kubernetes cluster

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

setup_kernel_modules() {
    log "Setting up kernel modules for Kubernetes..."
    modprobe br_netfilter || true
    modprobe overlay || true
    cat > /etc/modules-load.d/k8s.conf << EOF
br_netfilter
overlay
EOF
    success "Kernel modules configured"
}

setup_sysctl() {
    log "Configuring sysctl parameters for Kubernetes..."
    cat > /etc/sysctl.d/k8s.conf << EOF
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
    sysctl --system > /dev/null 2>&1
    success "Sysctl parameters configured"
}

install_kubernetes_packages() {
    log "Installing Kubernetes packages..."
    cleanup_stale_nvidia_repo
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    apt-get update -qq
    log "Installing kubelet, kubeadm, and kubectl..."
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    apt-mark hold kubelet kubeadm kubectl || true
    verify_command "kubelet" "kubelet installation failed"
    verify_command "kubeadm" "kubeadm installation failed"
    verify_command "kubectl" "kubectl installation failed"
    success "Kubernetes packages installed"
    log "Installed versions:"
    log "  kubelet: $(kubelet --version)"
    log "  kubeadm: $(kubeadm version -o short)"
    log "  kubectl: $(kubectl version --client -o yaml | grep gitVersion | cut -d' ' -f4)"
}

initialize_cluster() {
    log "Initializing Kubernetes cluster..."
    if kubectl cluster-info &> /dev/null; then
        success "Kubernetes cluster already running"
        return 0
    fi
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    log "Using internal IP: $INTERNAL_IP"
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
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    if kubectl cluster-info &> /dev/null; then
        success "kubectl configured successfully"
    else
        error "kubectl configuration failed"
    fi
    log "Cluster information:"
    kubectl cluster-info
}

install_cni() {
    log "Installing Flannel CNI plugin..."
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    log "Waiting for Flannel pods to be ready..."
    wait_for_pods "app=flannel" "kube-flannel" 300
    success "Flannel CNI installed"
}

setup_single_node() {
    log "Configuring single-node cluster..."
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    success "Single-node cluster configured"
}

wait_for_cluster() {
    log "Waiting for cluster to be fully ready..."
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    wait_for_pods "component=kube-apiserver" "kube-system" 300
    wait_for_pods "component=kube-controller-manager" "kube-system" 300
    wait_for_pods "component=kube-scheduler" "kube-system" 300
    wait_for_pods "component=etcd" "kube-system" 300
    success "Kubernetes cluster is ready"
    log "Cluster status:"
    kubectl get nodes -o wide
    kubectl get pods -n kube-system
}

main() {
    log "Starting Kubernetes installation phase..."
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
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