#!/bin/bash

# Deploy June GPU Multi-Service Container with Tailscale Userspace Networking

set -e

echo "🚀 Deploying June GPU Services with Tailscale Userspace Networking"
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Build and push userspace image
echo "📦 Building userspace Docker image..."
cd "$(dirname "$0")"
docker build -f Dockerfile-userspace -t ozzuworld/june-gpu-userspace:latest .
docker push ozzuworld/june-gpu-userspace:latest

echo "🔄 Updating Virtual Kubelet to userspace mode..."
# Update Virtual Kubelet to userspace version
kubectl patch deployment virtual-kubelet-vast-python -n kube-system -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "virtual-kubelet",
          "image": "ozzuworld/virtual-kubelet-vast-python:userspace"
        }]
      }
    }
  }
}'

echo "⏳ Waiting for Virtual Kubelet to restart..."
kubectl wait --for=condition=ready pod -n kube-system -l app=virtual-kubelet-vast-python --timeout=120s

echo "🔧 Updating GPU services deployment..."
# Update GPU services to use userspace image and environment
kubectl patch deployment june-gpu-services -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "june-multi-gpu",
          "image": "ozzuworld/june-gpu-userspace:latest",
          "env": [
            {
              "name": "TAILSCALE_AUTH_KEY",
              "valueFrom": {
                "secretKeyRef": {
                  "name": "tailscale-auth",
                  "key": "TAILSCALE_AUTH_KEY"
                }
              }
            },
            {
              "name": "TAILSCALE_LOGIN_SERVER", 
              "valueFrom": {
                "secretKeyRef": {
                  "name": "tailscale-auth",
                  "key": "TAILSCALE_LOGIN_SERVER"
                }
              }
            },
            {
              "name": "TAILSCALE_TEST_ENDPOINT",
              "value": "http://june-orchestrator.june-services.svc.cluster.local:8080/health"
            }
          ]
        }]
      }
    }
  }
}'

echo "📊 Scaling deployment to 1 replica..."
kubectl -n june-services scale deploy/june-gpu-services --replicas=0
sleep 5
kubectl -n june-services scale deploy/june-gpu-services --replicas=1

echo "👀 Monitoring deployment..."
kubectl get pods -n june-services -w --field-selector=metadata.name!=postgresql-0 &
PID=$!

# Wait up to 10 minutes for pod to be ready
echo "⏱️  Waiting for pod to be ready (timeout: 10 minutes)..."
if kubectl wait --for=condition=ready pod -n june-services -l app=june-gpu-services --timeout=600s; then
    echo "✅ GPU services pod is ready!"
    
    # Get pod name and show logs
    POD_NAME=$(kubectl get pods -n june-services -l app=june-gpu-services -o jsonpath='{.items[0].metadata.name}')
    echo "📋 Pod logs (last 20 lines):"
    kubectl logs -n june-services "$POD_NAME" --tail=20
    
    echo ""
    echo "🎉 Deployment successful!"
    echo "📱 To monitor: kubectl logs -f -n june-services $POD_NAME"
    echo "🔍 To debug: kubectl exec -it -n june-services $POD_NAME -- bash"
    echo "🌐 To test Tailscale: kubectl exec -it -n june-services $POD_NAME -- tailscale status"
else
    echo "❌ Pod failed to become ready within 10 minutes"
    POD_NAME=$(kubectl get pods -n june-services -l app=june-gpu-services -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "none")
    if [ "$POD_NAME" != "none" ]; then
        echo "📋 Pod logs for debugging:"
        kubectl logs -n june-services "$POD_NAME" --tail=50
    fi
    echo "🔍 Check Virtual Kubelet logs: kubectl logs -n kube-system -l app=virtual-kubelet-vast-python"
fi

# Stop monitoring
kill $PID 2>/dev/null || true

echo "✨ Deployment script completed"
