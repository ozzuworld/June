#!/bin/bash
# GPU Operator Installation with Time-Slicing
# Run after install-core-infrastructure.sh
# Usage: ./install-gpu-operator.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }

echo "======================================================"
echo "🎮 GPU Operator Installation with Time-Slicing"
echo "======================================================"
echo ""

# Check for NVIDIA GPU
if ! lspci | grep -i nvidia &> /dev/null; then
    log_warning "No NVIDIA GPU detected!"
    read -p "Continue anyway? (y/n): " CONTINUE
    [[ ! $CONTINUE =~ ^[Yy]$ ]] && exit 0
fi

# Configuration
read -p "GPU time-slicing replicas (2-8) [2]: " GPU_REPLICAS
GPU_REPLICAS=${GPU_REPLICAS:-2}

# Install Helm if not present
if ! command -v helm &> /dev/null; then
    log_info "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Add NVIDIA repo
log_info "Adding NVIDIA Helm repository..."
helm repo add nvidia https://nvidia.github.io/gpu-operator
helm repo update

# Create namespace
kubectl create namespace gpu-operator || true
kubectl label --overwrite namespace gpu-operator pod-security.kubernetes.io/enforce=privileged

# Install GPU Operator
log_info "Installing GPU Operator (this may take 5-10 minutes)..."
LATEST_VERSION=$(helm search repo nvidia/gpu-operator --versions | grep gpu-operator | head -1 | awk '{print $2}')

helm install gpu-operator nvidia/gpu-operator \
    --wait --timeout 15m \
    --namespace gpu-operator \
    --version=$LATEST_VERSION \
    --set driver.enabled=true \
    --set toolkit.enabled=true \
    --set devicePlugin.enabled=true

log_success "GPU Operator installed!"

# Wait for device plugin
log_info "Waiting for device plugin to be ready..."
kubectl wait --for=condition=ready pod \
    -n gpu-operator \
    -l app=nvidia-device-plugin-daemonset \
    --timeout=600s || log_warning "Device plugin taking longer than expected"

sleep 30

# Configure time-slicing
log_info "Configuring GPU time-slicing with ${GPU_REPLICAS} replicas..."

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing-config
  namespace: gpu-operator
data:
  any: |-
    version: v1
    flags:
      migStrategy: none
    sharing:
      timeSlicing:
        resources:
        - name: nvidia.com/gpu
          replicas: ${GPU_REPLICAS}
EOF

# Apply to ClusterPolicy
kubectl patch clusterpolicy cluster-policy \
    -n gpu-operator \
    --type merge \
    -p '{"spec": {"devicePlugin": {"config": {"name": "time-slicing-config", "default": "any"}}}}'

log_success "Time-slicing configuration applied!"

# Restart device plugin
log_info "Restarting device plugin to apply time-slicing..."
kubectl delete pods -n gpu-operator -l app=nvidia-device-plugin-daemonset || true
sleep 20

kubectl wait --for=condition=ready pod \
    -n gpu-operator \
    -l app=nvidia-device-plugin-daemonset \
    --timeout=300s

sleep 20

# Verify
log_info "Verifying GPU time-slicing..."
GPU_ALLOCATABLE=$(kubectl get nodes -o json | jq -r '.items[].status.allocatable."nvidia.com/gpu" // "0"' | head -1)

if [ "$GPU_ALLOCATABLE" -ge "$GPU_REPLICAS" ]; then
    log_success "GPU time-slicing is ACTIVE! ($GPU_ALLOCATABLE virtual GPUs)"
else
    log_warning "GPU time-slicing may still be activating (found $GPU_ALLOCATABLE GPUs, expected $GPU_REPLICAS)"
fi

# Label nodes
kubectl label nodes --all gpu=true --overwrite

echo ""
echo "======================================================"
log_success "GPU Operator Installation Complete!"
echo "======================================================"
echo ""
echo "✅ GPU Configuration:"
echo "  Virtual GPUs: $GPU_ALLOCATABLE"
echo "  Time-slicing replicas: $GPU_REPLICAS"
echo ""
echo "🔍 Verify GPU availability:"
echo "  kubectl get nodes -o json | jq '.items[].status.allocatable.\"nvidia.com/gpu\"'"
echo ""
echo "🧪 Test GPU allocation:"
echo "  kubectl run gpu-test --rm -i --image=nvidia/cuda:11.0-base --restart=Never -- nvidia-smi"
echo ""
echo "======================================================"