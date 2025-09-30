#!/bin/bash
# GPU Troubleshooting and Fix Script for Kubernetes
# Diagnoses and fixes NVIDIA GPU Operator issues

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "🔧 GPU Troubleshooting & Fix Script"
echo "===================================="
echo ""

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "ok") echo -e "${GREEN}✅ $message${NC}" ;;
        "warn") echo -e "${YELLOW}⚠️  $message${NC}" ;;
        "error") echo -e "${RED}❌ $message${NC}" ;;
        "info") echo -e "${BLUE}ℹ️  $message${NC}" ;;
    esac
}

# Step 1: Check network connectivity
echo "🌐 Step 1: Checking Network Connectivity"
echo "========================================"

print_status "info" "Testing connection to nvcr.io..."
if curl -I --max-time 10 https://nvcr.io &> /dev/null; then
    print_status "ok" "Can reach nvcr.io"
else
    print_status "error" "Cannot reach nvcr.io - Network or DNS issue"
    echo "Trying to fix DNS..."
    
    # Fix DNS
    cat > /etc/resolv.conf << EOF
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
EOF
    
    print_status "info" "DNS updated, retesting..."
    if curl -I --max-time 10 https://nvcr.io &> /dev/null; then
        print_status "ok" "Connection fixed!"
    else
        print_status "error" "Still cannot reach nvcr.io - may need to check firewall"
    fi
fi

# Step 2: Check GPU hardware
echo ""
echo "🎮 Step 2: Checking GPU Hardware"
echo "================================"

if command -v nvidia-smi &> /dev/null; then
    print_status "ok" "nvidia-smi found"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
else
    print_status "error" "nvidia-smi not found - NVIDIA drivers not installed"
    echo "Installing NVIDIA drivers..."
    
    # Detect Ubuntu version
    UBUNTU_VERSION=$(lsb_release -rs)
    
    # Install drivers
    apt-get update
    apt-get install -y ubuntu-drivers-common
    ubuntu-drivers autoinstall
    
    print_status "warn" "NVIDIA drivers installed - REBOOT REQUIRED"
    read -p "Reboot now? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        reboot
    fi
fi

# Step 3: Check containerd configuration
echo ""
echo "🐳 Step 3: Checking Containerd Configuration"
echo "==========================================="

print_status "info" "Checking containerd config..."

# Backup original config
cp /etc/containerd/config.toml /etc/containerd/config.toml.backup

# Generate new config with proper settings
containerd config default > /etc/containerd/config.toml

# Enable SystemdCgroup
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Restart containerd
systemctl restart containerd
systemctl status containerd --no-pager | head -5

print_status "ok" "Containerd reconfigured and restarted"

# Step 4: Check GPU Operator status
echo ""
echo "📦 Step 4: Checking GPU Operator Status"
echo "======================================="

if kubectl get namespace gpu-operator &> /dev/null; then
    print_status "ok" "GPU Operator namespace exists"
    
    echo ""
    print_status "info" "GPU Operator pods status:"
    kubectl get pods -n gpu-operator
    
    # Check for image pull errors
    echo ""
    print_status "info" "Checking for ImagePullBackOff pods..."
    FAILED_PODS=$(kubectl get pods -n gpu-operator --field-selector=status.phase!=Running,status.phase!=Succeeded -o jsonpath='{.items[*].metadata.name}')
    
    if [ -n "$FAILED_PODS" ]; then
        print_status "warn" "Found problematic pods: $FAILED_PODS"
        
        for pod in $FAILED_PODS; do
            echo ""
            print_status "info" "Describing pod: $pod"
            kubectl describe pod $pod -n gpu-operator | tail -30
        done
    fi
else
    print_status "warn" "GPU Operator not installed"
fi

# Step 5: Fix image pull issues
echo ""
echo "🔧 Step 5: Fixing Image Pull Issues"
echo "===================================="

print_status "info" "Cleaning up failed GPU Operator installation..."

# Delete GPU Operator if it exists
if helm list -n gpu-operator | grep -q gpu-operator; then
    print_status "info" "Uninstalling existing GPU Operator..."
    helm uninstall gpu-operator -n gpu-operator --wait
    sleep 10
fi

# Clean up namespace
kubectl delete namespace gpu-operator --ignore-not-found=true --wait=true

print_status "ok" "Cleanup complete"

# Step 6: Reinstall GPU Operator with fixes
echo ""
echo "🚀 Step 6: Reinstalling GPU Operator"
echo "===================================="

# Ensure Helm is installed
if ! command -v helm &> /dev/null; then
    print_status "info" "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 | bash
fi

# Add NVIDIA Helm repo
print_status "info" "Adding NVIDIA Helm repository..."
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia || true
helm repo update

# Create namespace with proper labels
print_status "info" "Creating gpu-operator namespace..."
kubectl create namespace gpu-operator || true
kubectl label --overwrite namespace gpu-operator pod-security.kubernetes.io/enforce=privileged

# Check if NFD is already running
NFD_EXISTS=$(kubectl get nodes -o json | jq '.items[].metadata.labels | keys | any(startswith("feature.node.kubernetes.io"))' 2>/dev/null || echo "false")

NFD_DISABLE=""
if [ "$NFD_EXISTS" = "true" ]; then
    print_status "info" "NFD already running, disabling in GPU Operator"
    NFD_DISABLE="--set nfd.enabled=false"
fi

# Install GPU Operator with optimized settings
print_status "info" "Installing GPU Operator v25.3.4..."

helm install gpu-operator \
    --wait \
    --timeout 15m \
    --namespace gpu-operator \
    nvidia/gpu-operator \
    --version=v25.3.4 \
    --set driver.enabled=true \
    --set toolkit.enabled=true \
    --set devicePlugin.enabled=true \
    --set dcgmExporter.enabled=true \
    --set gfd.enabled=true \
    --set migManager.enabled=true \
    --set nodeStatusExporter.enabled=true \
    --set gds.enabled=false \
    --set vfioManager.enabled=true \
    --set sandboxWorkloads.enabled=false \
    --set vgpuManager.enabled=false \
    --set vgpuDeviceManager.enabled=false \
    --set ccManager.enabled=false \
    --set operator.defaultRuntime=containerd \
    $NFD_DISABLE

print_status "ok" "GPU Operator installation initiated"

# Step 7: Monitor installation
echo ""
echo "⏳ Step 7: Monitoring Installation Progress"
echo "=========================================="

print_status "info" "Waiting for GPU Operator components (this may take 5-10 minutes)..."
echo ""

# Function to check pod status
check_component() {
    local component=$1
    local timeout=$2
    
    print_status "info" "Waiting for $component..."
    
    if kubectl wait --for=condition=ready pods \
        --selector=app=$component \
        --namespace=gpu-operator \
        --timeout=${timeout}s 2>&1 | grep -q "condition met"; then
        print_status "ok" "$component is ready"
        return 0
    else
        print_status "warn" "$component not ready yet"
        return 1
    fi
}

# Wait for key components
check_component "nvidia-driver-daemonset" 600 || true
sleep 30
check_component "nvidia-container-toolkit-daemonset" 300 || true
sleep 30
check_component "nvidia-device-plugin-daemonset" 300 || true

# Step 8: Verify GPU availability
echo ""
echo "✅ Step 8: Verifying GPU Availability"
echo "===================================="

print_status "info" "Checking GPU resources in cluster..."
sleep 60  # Give time for resources to register

GPU_COUNT=$(kubectl get nodes -o jsonpath='{.items[*].status.capacity.nvidia\.com/gpu}' | tr ' ' '+' | bc 2>/dev/null || echo "0")

if [ "$GPU_COUNT" -gt 0 ]; then
    print_status "ok" "GPU resources detected! Count: $GPU_COUNT"
    
    echo ""
    print_status "info" "Node GPU capacity:"
    kubectl describe nodes | grep -A 5 "Capacity:" | grep "nvidia.com/gpu"
else
    print_status "warn" "GPU resources not yet visible"
    echo ""
    print_status "info" "Current GPU Operator status:"
    kubectl get pods -n gpu-operator -o wide
    
    echo ""
    print_status "info" "Check device plugin logs:"
    DEVICE_PLUGIN_POD=$(kubectl get pods -n gpu-operator -l app=nvidia-device-plugin-daemonset -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$DEVICE_PLUGIN_POD" ]; then
        kubectl logs $DEVICE_PLUGIN_POD -n gpu-operator --tail=50
    fi
fi

# Step 9: Create test workload
echo ""
echo "🧪 Step 9: Creating GPU Test Workload"
echo "====================================="

if [ "$GPU_COUNT" -gt 0 ]; then
    print_status "info" "Creating GPU test pod..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-test
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: cuda-container
    image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
    resources:
      limits:
        nvidia.com/gpu: 1
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
EOF
    
    print_status "ok" "Test pod created"
    print_status "info" "Monitor with: kubectl logs gpu-test -f"
else
    print_status "warn" "Skipping test workload - GPU resources not available yet"
fi

# Step 10: Summary and next steps
echo ""
echo "📋 Summary & Next Steps"
echo "======================"

echo ""
print_status "info" "Current Status:"
kubectl get pods -n gpu-operator

echo ""
print_status "info" "Useful Commands:"
echo "  • Check GPU Operator status: kubectl get pods -n gpu-operator"
echo "  • Check GPU resources: kubectl describe nodes | grep nvidia.com/gpu"
echo "  • View device plugin logs: kubectl logs -l app=nvidia-device-plugin-daemonset -n gpu-operator"
echo "  • View driver logs: kubectl logs -l app=nvidia-driver-daemonset -n gpu-operator"
echo "  • Test GPU workload: kubectl logs gpu-test -f"
echo "  • Manual test: kubectl run gpu-test-manual --image=nvidia/cuda:12.2.2-base-ubuntu22.04 --rm -it --restart=Never --limits nvidia.com/gpu=1 -- nvidia-smi"

echo ""
if [ "$GPU_COUNT" -gt 0 ]; then
    print_status "ok" "GPU setup complete and verified! ✨"
else
    print_status "warn" "GPU Operator installed but resources not yet visible"
    print_status "info" "This is normal - pods may still be initializing"
    print_status "info" "Wait 5-10 minutes and check again with:"
    echo "  kubectl describe nodes | grep nvidia.com/gpu"
fi

echo ""
echo "===================================="