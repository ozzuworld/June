#!/bin/bash
# Setup script for June platform Tailscale integration
# Deploys all necessary components for GPU services to connect via headscale VPN

set -e

echo "🚀 June Platform - Tailscale Integration Setup"
echo "================================================="
echo

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found. Please install kubectl first."
    exit 1
fi

# Check if we can connect to the cluster
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes cluster. Check your kubeconfig."
    exit 1
fi

echo "✅ Kubernetes cluster connection verified"
echo

# Step 1: Deploy Tailscale authentication secret
echo "📋 Step 1: Deploying Tailscale authentication secret..."
kubectl apply -f k8s/tailscale/tailscale-auth-secret.yaml
echo "✅ Tailscale auth secret deployed"
echo

# Step 2: Verify headscale is running
echo "📋 Step 2: Checking headscale deployment..."
if kubectl get deployment -n headscale headscale &> /dev/null; then
    echo "✅ Headscale deployment found"
    
    # Check if headscale is ready
    if kubectl wait --for=condition=available --timeout=60s deployment/headscale -n headscale &> /dev/null; then
        echo "✅ Headscale is ready and available"
    else
        echo "⚠️  Headscale deployment exists but may not be ready"
    fi
else
    echo "❌ Headscale deployment not found. Please deploy headscale first:"
    echo "   kubectl apply -f k8s/headscale/headscale-all.yaml"
    exit 1
fi
echo

# Step 3: Check Tailscale operator (if using K8s services exposure)
echo "📋 Step 3: Checking Tailscale operator (optional)..."
if kubectl get deployment -n tailscale operator &> /dev/null; then
    echo "✅ Tailscale operator found"
else
    echo "ℹ️  Tailscale operator not found (OK - using direct headscale connection)"
fi
echo

# Step 4: Deploy Virtual Kubelet for vast.ai (if not already deployed)
echo "📋 Step 4: Checking Virtual Kubelet deployment..."
if kubectl get deployment -n kube-system virtual-kubelet-vast &> /dev/null; then
    echo "✅ Virtual Kubelet deployment found"
else
    echo "⚠️  Virtual Kubelet not found. Deploying..."
    
    # Check if vast-credentials secret exists
    if ! kubectl get secret -n kube-system vast-credentials &> /dev/null; then
        echo "❌ vast-credentials secret not found. Please create it first:"
        echo "   kubectl create secret generic vast-credentials --from-literal=api-key=YOUR_VAST_API_KEY -n kube-system"
        exit 1
    fi
    
    kubectl apply -f k8s/vast-gpu/rbac.yaml
    kubectl apply -f k8s/vast-gpu/vast-provider-config.yaml
    kubectl apply -f k8s/vast-gpu/virtual-kubelet-deployment.yaml
    echo "✅ Virtual Kubelet deployed"
fi
echo

# Step 5: Wait for Virtual Kubelet to be ready
echo "📋 Step 5: Waiting for Virtual Kubelet to be ready..."
if kubectl wait --for=condition=available --timeout=120s deployment/virtual-kubelet-vast -n kube-system &> /dev/null; then
    echo "✅ Virtual Kubelet is ready"
else
    echo "⚠️  Virtual Kubelet deployment timeout (may still be starting)"
fi
echo

# Step 6: Check if vast-gpu-node-python is available
echo "📋 Step 6: Checking virtual GPU node..."
for i in {1..30}; do
    if kubectl get node vast-gpu-node-python &> /dev/null; then
        echo "✅ Virtual GPU node 'vast-gpu-node-python' is available"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "⚠️  Virtual GPU node not yet available (may still be initializing)"
        echo "    Check Virtual Kubelet logs: kubectl logs -n kube-system deployment/virtual-kubelet-vast"
    else
        echo "    Waiting for virtual GPU node... ($i/30)"
        sleep 5
    fi
done
echo

# Step 7: Deploy GPU services with Tailscale integration
echo "📋 Step 7: Deploying GPU services with Tailscale integration..."
kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml
echo "✅ GPU services deployment submitted"
echo

# Step 8: Monitor deployment
echo "📋 Step 8: Monitoring GPU services deployment..."
echo "This may take several minutes as it provisions a vast.ai GPU instance..."
echo

echo "📊 Deployment Status:"
kubectl get pods -n june-services -l app=june-gpu-services -o wide
echo

echo "📊 Virtual Kubelet Logs (last 20 lines):"
kubectl logs -n kube-system deployment/virtual-kubelet-vast --tail=20 || echo "No logs available yet"
echo

echo "🎯 Next Steps:"
echo "1. Monitor the deployment:"
echo "   kubectl get pods -n june-services -l app=june-gpu-services -w"
echo
echo "2. Check Virtual Kubelet logs for provisioning progress:"
echo "   kubectl logs -n kube-system deployment/virtual-kubelet-vast -f"
echo
echo "3. Once pod is Running, check Tailscale connection:"
echo "   kubectl logs -n june-services deployment/june-gpu-services"
echo
echo "4. Verify headscale connectivity:"
echo "   kubectl -n headscale exec deployment/headscale -- headscale nodes list"
echo
echo "5. Test service connectivity (once pod is ready):"
echo "   kubectl port-forward -n june-services service/june-gpu-services 8000:8000 8001:8001"
echo "   curl http://localhost:8000/healthz"
echo "   curl http://localhost:8001/healthz"
echo
echo "🎉 Tailscale integration setup completed!"
echo "   The GPU service will automatically connect to your headscale VPN"
echo "   and be able to communicate with june-orchestrator and livekit services."
