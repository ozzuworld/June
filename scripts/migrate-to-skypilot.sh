#!/bin/bash
# Automated migration from Virtual Kubelet to SkyPilot

set -e

echo "🔄 Migrating from Virtual Kubelet to SkyPilot"
echo "=============================================="

# Step 1: Clean up Virtual Kubelet
echo ""
echo "Step 1: Removing Virtual Kubelet components..."
kubectl delete deployment virtual-kubelet-vast -n kube-system --ignore-not-found
kubectl delete serviceaccount virtual-kubelet-vast -n kube-system --ignore-not-found
kubectl delete clusterrole virtual-kubelet-vast --ignore-not-found
kubectl delete clusterrolebinding virtual-kubelet-vast --ignore-not-found
kubectl delete configmap vast-provider-config -n kube-system --ignore-not-found
kubectl delete secret vast-api-secret -n kube-system --ignore-not-found

# Delete virtual node
kubectl delete node vast-gpu-node-python --ignore-not-found

echo "✅ Virtual Kubelet removed"

# Step 2: Install SkyPilot
echo ""
echo "Step 2: Installing SkyPilot..."
if ! command -v sky &> /dev/null; then
    pip install "skypilot[vast]" --break-system-packages
fi

echo "✅ SkyPilot installed"

# Step 3: Run phase 12
echo ""
echo "Step 3: Running installation phase..."
./scripts/install/12-skypilot.sh "$(pwd)"

echo ""
echo "✅ Migration complete!"
echo ""
echo "📋 Next steps:"
echo "  1. Deploy GPU services: ./scripts/skypilot/deploy-gpu-services.sh"
echo "  2. Check status: sky status --all"
echo "  3. View logs: sky logs june-gpu-services -f"