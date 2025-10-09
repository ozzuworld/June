#!/bin/bash

# STUNner Operator Installation Script for June Platform
# This script installs the STUNner operator which is required for TURN/STUN functionality

set -e

echo "🚀 Installing STUNner Operator for June Platform..."

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl is not installed or not in PATH"
    exit 1
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes cluster"
    exit 1
fi

echo "✅ Kubernetes cluster is accessible"

# Install STUNner operator using Helm (if Helm is available)
if command -v helm &> /dev/null; then
    echo "📦 Installing STUNner operator using Helm..."
    
    # Add STUNner Helm repository
    helm repo add stunner https://l7mp.io/stunner
    helm repo update
    
    # Install STUNner gateway operator
    helm install stunner-gateway-operator stunner/stunner-gateway-operator \
        --create-namespace \
        --namespace stunner-system \
        --wait
    
    echo "✅ STUNner operator installed via Helm"
else
    echo "📦 Installing STUNner operator using kubectl..."
    
    # Install STUNner operator using kubectl
    kubectl apply -f https://raw.githubusercontent.com/l7mp/stunner/main/deploy/stunner-gateway-operator-ns.yaml
    kubectl apply -f https://raw.githubusercontent.com/l7mp/stunner/main/deploy/stunner-gateway-operator.yaml
    
    echo "⏳ Waiting for STUNner operator to be ready..."
    kubectl wait --for=condition=available deployment/stunner-gateway-operator-controller-manager \
        -n stunner-system --timeout=300s
    
    echo "✅ STUNner operator installed via kubectl"
fi

# Verify installation
echo "🔍 Verifying STUNner operator installation..."

# Check if stunner-system namespace exists
if ! kubectl get namespace stunner-system &> /dev/null; then
    echo "❌ stunner-system namespace not found"
    exit 1
fi

# Check if operator pod is running
if ! kubectl get pods -n stunner-system | grep -q "Running"; then
    echo "❌ STUNner operator pod is not running"
    kubectl get pods -n stunner-system
    exit 1
fi

# Check if CRDs are installed
CRDS=("gatewayclasses.gateway.networking.k8s.io" "gateways.gateway.networking.k8s.io" "gatewayconfigs.stunner.l7mp.io" "udproutes.stunner.l7mp.io")

for crd in "${CRDS[@]}"; do
    if ! kubectl get crd "$crd" &> /dev/null; then
        echo "❌ Required CRD $crd not found"
        exit 1
    fi
done

echo "✅ All required CRDs are installed"

# Show operator status
echo "📊 STUNner Operator Status:"
kubectl get pods -n stunner-system

echo ""
echo "🎉 STUNner operator installation completed successfully!"
echo ""
echo "Next steps:"
echo "1. Apply STUNner manifests: kubectl apply -f k8s/stunner-manifests.yaml"
echo "2. Apply June services: kubectl apply -f k8s/complete-manifests.yaml"
echo "3. Test TURN/STUN connectivity with: python3 scripts/test-turn-server.py"
echo ""